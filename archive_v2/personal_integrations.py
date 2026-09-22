"""Owner-only personal input, voice storage and Web Push delivery."""
import base64
import email
import hashlib
import hmac
import imaplib
import json
import os
import secrets
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from email import policy
from pathlib import Path
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from fastapi import Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pywebpush import webpush, WebPushException


def install(app, root, web, db, create_item):
    secret_dir = root / 'personal-private'
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(secret_dir, 0o700)
    audio_dir = secret_dir / 'voice'
    audio_dir.mkdir(mode=0o700, exist_ok=True)
    keyfile = secret_dir / 'key'
    if not keyfile.exists():
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f: f.write(Fernet.generate_key())
    key = keyfile.read_bytes()
    cipher = Fernet(key)
    configfile = secret_dir / 'settings.enc'
    passwordfile = secret_dir / 'password.json'
    vapidfile = secret_dir / 'vapid.pem'
    if not vapidfile.exists():
        k = ec.generate_private_key(ec.SECP256R1())
        fd = os.open(vapidfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    vapidkey = serialization.load_pem_private_key(vapidfile.read_bytes(), password=None)
    public = base64.urlsafe_b64encode(vapidkey.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()
    lock = threading.Lock()
    stop = threading.Event()
    failures = {}
    mail_state = {'status':'not_configured', 'last_sync':None, 'imported':0}

    def config():
        return json.loads(cipher.decrypt(configfile.read_bytes())) if configfile.exists() else {}

    def save_config(value):
        tmp = configfile.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f: f.write(cipher.encrypt(json.dumps(value).encode()))
        tmp.replace(configfile)

    def authorized(request):
        try:
            value, signature = request.cookies.get('personal_session','').rsplit('.',1)
            session_key=key+passwordfile.read_bytes()
            return int(value) > time.time() and hmac.compare_digest(signature,hmac.new(session_key,value.encode(),hashlib.sha256).hexdigest())
        except (ValueError,TypeError,OSError): return False

    def require(request):
        if not passwordfile.exists(): raise HTTPException(503,'ابتدا قفل دستیار را با دستور راه‌اندازی روی سرور فعال کن.')
        if not authorized(request): raise HTTPException(401,'ورود به دستیار لازم است')

    @app.middleware('http')
    async def protect_personal(request, call_next):
        path = request.url.path
        protected = path.startswith('/api/personal/') or path in ('/personal','/personal/','/personal/widget')
        excluded = path in ('/api/personal/auth/status','/api/personal/auth/login')
        if protected and passwordfile.exists() and not excluded and not authorized(request):
            if path.startswith('/api/'):
                return JSONResponse({'detail':'ورود به دستیار لازم است'},status_code=401)
                return HTMLResponse((web/'personal-login.html').read_text(),headers={'Cache-Control':'no-store'})
        if protected and request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail':'Invalid origin'},status_code=403)
        response=await call_next(request)
        if protected: response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/personal/auth/status')
    def auth_status(request:Request):
        return {'locked':passwordfile.exists(),'authenticated':authorized(request)}

    @app.post('/api/personal/auth/login')
    def login(request:Request, payload:dict=Body(...)):
        if not passwordfile.exists(): raise HTTPException(503,'قفل هنوز تنظیم نشده است')
        client = request.client.host if request.client else 'unknown'
        current = time.time()
        attempts = [v for v in failures.get(client,[]) if v > current-300]
        failures[client] = attempts
        if len(attempts) >= 10: raise HTTPException(429,'پنج دقیقه بعد دوباره تلاش کن')
        p = passwordfile.read_text(); stored = json.loads(p)
        candidate = hashlib.scrypt(str(payload.get('password','')).encode(),salt=bytes.fromhex(stored['salt']),n=16384,r=8,p=1).hex()
        if not hmac.compare_digest(candidate,stored['hash']):
            attempts.append(current)
            raise HTTPException(401,'رمز نادرست است')
        failures.pop(client,None)
        expires = str(int(current+7*86400))
        token = expires+'.'+hmac.new(key+passwordfile.read_bytes(),expires.encode(),hashlib.sha256).hexdigest()
        response = JSONResponse({'ok':True})
        response.set_cookie('personal_session',token,httponly=True,secure=True,samesite='strict',max_age=7*86400,path='/')
        return response

    @app.post('/api/personal/auth/logout')
    def logout():
        r = JSONResponse({'ok':True}); r.delete_cookie('personal_session',path='/'); return r

    def startup():
        with db() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS personal_push(id TEXT PRIMARY KEY, subscription TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS personal_deliveries(subscription_id TEXT,item_id TEXT,kind TEXT,due TEXT,PRIMARY KEY(subscription_id,item_id,kind,due));
            CREATE TABLE IF NOT EXISTS personal_mail_seen(account TEXT,message_key TEXT,item_id TEXT,PRIMARY KEY(account,message_key));
            CREATE TABLE IF NOT EXISTS personal_voice(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,mime TEXT NOT NULL,filename TEXT NOT NULL);
            ''')
        stop.clear()
        threading.Thread(target=background,daemon=True,name='personal-inputs').start()

    def push_send(subscription, payload):
        c = config()
        return webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=str(vapidfile),vapid_claims={'sub':c.get('push_contact','mailto:admin@example.com')},timeout=10,ttl=3600)

    def deliver_due():
        current = datetime.now(timezone.utc)
        with db() as con:
            rows = list(con.execute("SELECT id,title,due_at,follow_up_at,status FROM personal_items WHERE status NOT IN ('done','archived')"))
            subs = list(con.execute('SELECT * FROM personal_push'))
        for row in rows:
            for kind in ('due_at','follow_up_at'):
                raw = row[kind]
                if not raw: continue
                if kind=='follow_up_at' and row['status']!='waiting': continue
                try:
                    due = datetime.fromisoformat(raw.replace('Z','+00:00'))
                    if due.tzinfo is None: due=due.replace(tzinfo=timezone(timedelta(hours=3,minutes=30)))
                except ValueError: continue
                if due>current: continue
                for sub in subs:
                    with db() as con:
                        sent=con.execute('SELECT 1 FROM personal_deliveries WHERE subscription_id=? AND item_id=? AND kind=? AND due=?',(sub['id'],row['id'],kind,raw)).fetchone()
                    if sent: continue
                    try:
                        push_send(json.loads(sub['subscription']),{'title':'همراه من','body':'یک کار یا پیگیری به موعد رسیده است.','tag':row['id']+kind,'url':'/personal'})
                    except WebPushException as e:
                        if e.response is not None and e.response.status_code in (404,410):
                            with db() as con: con.execute('DELETE FROM personal_push WHERE id=?',(sub['id'],))
                        continue
                    except Exception: continue
                    with db() as con:
                        con.execute('INSERT OR IGNORE INTO personal_deliveries VALUES(?,?,?,?)',(sub['id'],row['id'],kind,raw))

    def validate_mail(c):
        host=str(c.get('host','')).strip().lower()
        # Fixed providers avoid turning the credential form into an arbitrary network client.
        if host not in ('imap.gmail.com','imap.mail.yahoo.com','imap.mail.me.com'):
            raise HTTPException(400,'سرویس ایمیل پشتیبانی نمی‌شود')
        if not str(c.get('username','')).strip() or not str(c.get('password','')):
            raise HTTPException(400,'ایمیل و رمز برنامه لازم است')
        return host

    def sync_mail(test_config=None):
        if not lock.acquire(blocking=False): return {'busy':True}
        connection=None
        try:
            c=test_config or config().get('mail',{})
            host=validate_mail(c)
            account=host+'|'+c['username'].strip().lower()
            connection=imaplib.IMAP4_SSL(host,993,ssl_context=ssl.create_default_context(),timeout=20)
            connection.login(c['username'],c['password'])
            status,_=connection.select('INBOX',readonly=True)
            if status!='OK': raise ValueError('inbox')
            if test_config: return {'ok':True}
            since=(datetime.now(timezone.utc)-timedelta(days=7)).strftime('%d-%b-%Y')
            status,result=connection.uid('search',None,'SINCE',since)
            if status!='OK': raise ValueError('search')
            validity=connection.response('UIDVALIDITY')[1][0].decode()
            imported=0
            for uid in result[0].split()[-30:]:
                message_key=validity+':'+uid.decode()
                with db() as con:
                    if con.execute('SELECT 1 FROM personal_mail_seen WHERE account=? AND message_key=?',(account,message_key)).fetchone(): continue
                status,parts=connection.uid('fetch',uid,'(BODY.PEEK[]<0.262144>)')
                raw=next((v[1] for v in parts if isinstance(v,tuple)),None)
                if status!='OK' or not raw: continue
                message=email.message_from_bytes(raw,policy=policy.default)
                body=message.get_body(preferencelist=('plain',)) if message.is_multipart() else message
                content=body.get_content() if body and body.get_content_type()=='text/plain' else 'متن ساده موجود نیست؛ ایمیل اصلی را بررسی کن.'
                item=create_item({'title':str(message.get('Subject') or 'ایمیل بدون عنوان')[:240], 'details':('فرستنده: '+str(message.get('From',''))+'\nتاریخ: '+str(message.get('Date',''))+'\n\n'+str(content))[:4000], 'item_type':'email','source':'imap','status':'inbox','metadata':{'message_id':str(message.get('Message-ID','')),'account':c['username']}})['item']
                with db() as con: con.execute('INSERT OR IGNORE INTO personal_mail_seen VALUES(?,?,?)',(account,message_key,item['id']))
                imported+=1
            mail_state.update(status='connected',last_sync=datetime.now(timezone.utc).isoformat(),imported=imported)
            return {'ok':True,'imported':imported}
        finally:
            if connection:
                try: connection.logout()
                except Exception: pass
            lock.release()

    def background():
        last_mail=0
        while not stop.wait(15):
            if not passwordfile.exists(): continue
            try:
                c=config()
                if c.get('mail',{}).get('enabled') and time.monotonic()-last_mail>=300:
                    last_mail=time.monotonic()
                    try: sync_mail()
                    except Exception: mail_state['status']='error'
                deliver_due()
            except Exception:
                # Credentials and message content must never be written to logs.
                pass

    @app.get('/api/personal/integrations')
    def integration_status(request:Request):
        require(request)
        c=config(); mail=c.get('mail',{})
        return {'mail':{'enabled':bool(mail.get('enabled')),'username':mail.get('username',''),'host':mail.get('host','imap.gmail.com'),**mail_state},'push_public_key':public,'push_contact':c.get('push_contact',''),'voice_max_mb':20}

    @app.post('/api/personal/integrations/mail')
    def configure_mail(request:Request,payload:dict=Body(...)):
        require(request)
        old=config(); mail=old.get('mail',{})
        if payload.get('enabled') is False:
            old.pop('mail',None); save_config(old); mail_state.update(status='not_configured'); return {'ok':True}
        new={'host':str(payload.get('host','')),'username':str(payload.get('username','')).strip(),'password':str(payload.get('password') or mail.get('password','')),'enabled':True}
        validate_mail(new)
        try:
            result=sync_mail(new)
            if result.get('busy'): raise HTTPException(409,'همگام‌سازی در حال اجراست؛ کمی بعد ذخیره کن')
        except HTTPException: raise
        except Exception: raise HTTPException(400,'اتصال تأیید نشد؛ IMAP، رمز مخصوص برنامه و دسترسی اینترنت سرور را بررسی کن.')
        old['mail']=new; save_config(old); mail_state['status']='connected'
        return {'ok':True}

    @app.post('/api/personal/integrations/mail/sync')
    def manual_sync(request:Request):
        require(request)
        try: return sync_mail()
        except Exception: raise HTTPException(502,'دریافت ایمیل موفق نبود؛ تنظیمات اتصال را بررسی کن.')

    @app.post('/api/personal/push/subscribe')
    def subscribe(request:Request,payload:dict=Body(...)):
        require(request)
        sub=payload.get('subscription',{}); endpoint=str(sub.get('endpoint',''))
        parsed=urlparse(endpoint)
        host=parsed.hostname or ''
        allowed=host=='web.push.apple.com' or host.endswith('.push.apple.com') or host=='fcm.googleapis.com' or host=='updates.push.services.mozilla.com' or host.endswith('.notify.windows.com')
        if parsed.scheme!='https' or parsed.port not in (None,443) or parsed.username or not allowed:
            raise HTTPException(400,'نشانی سرویس اعلان معتبر نیست')
        if not isinstance(sub.get('keys'),dict) or not all(sub['keys'].get(k) for k in ('p256dh','auth')): raise HTTPException(400,'کلیدهای اعلان نامعتبرند')
        if len(json.dumps(sub))>4096: raise HTTPException(400,'اشتراک نامعتبر است')
        contact=str(payload.get('contact','')).strip()
        if not contact or '@' not in contact or '\n' in contact: raise HTTPException(400,'ایمیل تماس برای اعلان لازم است')
        c=config(); c['push_contact']='mailto:'+contact.removeprefix('mailto:'); save_config(c)
        sid=hashlib.sha256(endpoint.encode()).hexdigest()
        with db() as con: con.execute('INSERT OR REPLACE INTO personal_push VALUES(?,?)',(sid,json.dumps(sub)))
        return {'ok':True}

    @app.post('/api/personal/push/test')
    def push_test(request:Request,payload:dict=Body(...)):
        require(request)
        sid=hashlib.sha256(str(payload.get('endpoint','')).encode()).hexdigest()
        with db() as con: row=con.execute('SELECT subscription FROM personal_push WHERE id=?',(sid,)).fetchone()
        if not row: raise HTTPException(404,'ابتدا اعلان این دستگاه را فعال کن')
        try: push_send(json.loads(row[0]),{'title':'همراه من','body':'اعلان آزمایشی با موفقیت رسید.','url':'/personal','tag':'test'})
        except Exception: raise HTTPException(502,'ارسال اعلان موفق نبود؛ ارتباط سرور با سرویس Push را بررسی کن.')
        return {'ok':True}

    @app.post('/api/personal/push/unsubscribe')
    def unsubscribe(request:Request,payload:dict=Body(...)):
        require(request)
        sid=hashlib.sha256(str(payload.get('endpoint','')).encode()).hexdigest()
        with db() as con: con.execute('DELETE FROM personal_push WHERE id=?',(sid,))
        return {'ok':True}

    @app.post('/api/personal/voice')
    def voice_upload(request:Request,file:UploadFile=File(...)):
        require(request)
        mime=(file.content_type or '').split(';')[0]
        if mime not in ('audio/mp4','audio/mpeg','audio/wav','audio/x-wav','audio/webm','audio/ogg','audio/aac','audio/x-m4a'): raise HTTPException(400,'فایل صوتی پشتیبانی نمی‌شود')
        vid=str(uuid.uuid4()); path=audio_dir/vid; size=0
        try:
            with path.open('wb') as f:
                while True:
                    chunk=file.file.read(65536)
                    if not chunk: break
                    size+=len(chunk)
                    if size>20*1024*1024: raise HTTPException(413,'حداکثر حجم صدا ۲۰ مگابایت است')
                    f.write(chunk)
            if not size: raise HTTPException(400,'فایل خالی است')
            item=create_item({'title':'یادداشت صوتی · '+datetime.now(timezone(timedelta(hours=3,minutes=30))).strftime('%Y-%m-%d %H:%M'),'item_type':'note','source':'voice','details':'صدا ذخیره شده است؛ متن و کارهای مرتبط را پس از گوش‌دادن اضافه کن.','metadata':{'voice_id':vid}})['item']
            with db() as con: con.execute('INSERT INTO personal_voice VALUES(?,?,?,?)',(vid,item['id'],mime,Path(file.filename or 'voice').name[:200]))
        except Exception:
            path.unlink(missing_ok=True); raise
        return {'ok':True,'item':item}

    @app.get('/api/personal/voice/{vid}')
    def voice_play(vid:str,request:Request):
        require(request)
        with db() as con: row=con.execute('SELECT v.* FROM personal_voice v JOIN personal_items i ON i.id=v.item_id WHERE v.id=?',(vid,)).fetchone()
        if not row: raise HTTPException(404)
        return FileResponse(audio_dir/row['id'],media_type=row['mime'],headers={'Cache-Control':'no-store'})

    @app.get('/personal/widget',response_class=HTMLResponse)
    def widget(): return (web/'personal-widget.html').read_text()

    @app.get('/personal/manifest.webmanifest')
    def manifest():
        return JSONResponse({'id':'/personal','name':'همراه من','short_name':'همراه من','lang':'fa','dir':'rtl','start_url':'/personal','scope':'/personal','display':'standalone','background_color':'#f6f7fb','theme_color':'#5b6ff7','icons':[{'src':'/personal/icon-192.png','sizes':'192x192','type':'image/png'},{'src':'/personal/icon-512.png','sizes':'512x512','type':'image/png'}]})

    @app.get('/personal/icon-{size}.png')
    def app_icon(size:int):
        if size not in (192,512): raise HTTPException(404)
        return FileResponse(web/f'personal-icon-{size}.png',media_type='image/png')

    @app.get('/personal/sw.js')
    def sw(): return FileResponse(web/'personal-sw.js',media_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/personal'})

    @app.get('/personal/integrations.js')
    def js(): return FileResponse(web/'personal-integrations.js',media_type='application/javascript')

    return startup, stop.set

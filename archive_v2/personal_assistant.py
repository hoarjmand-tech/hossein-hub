"""Personal executive-assistant layer for Hossein Archive.

This module deliberately keeps intelligence advisory: it creates suggestions, but never
changes a Capture into a task, fact, commitment, decision or event without confirmation.
It uses only the Python standard library so the existing image can be upgraded without
pulling heavyweight AI dependencies. Optional speech-to-text can be attached later via
WHISPER_CMD; original audio is always retained as evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import uuid
import shutil
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse


TZ = timezone(timedelta(hours=3, minutes=30))
OPEN_ITEM = "status NOT IN ('done','archived')"


def install(app, root: Path, db, capture_fn, item_fn, fact_fn, now_fn):
    web=Path(__file__).parent/'web'
    def stamp():
        return now_fn()

    def clean(value, limit=4000):
        return str(value or "").strip()[:limit]

    def jload(value, default=None):
        try:
            return json.loads(value or "")
        except Exception:
            return {} if default is None else default

    def jd(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def row_dict(row):
        return dict(row) if row else None

    def local_today():
        return datetime.now(TZ).date()

    def parse_relative_date(text):
        low=text.casefold(); today=local_today()
        if any(x in low for x in ("امروز", "today")): return today.isoformat()
        if any(x in low for x in ("فردا", "tomorrow")): return (today+timedelta(days=1)).isoformat()
        if any(x in low for x in ("پس فردا", "day after tomorrow")): return (today+timedelta(days=2)).isoformat()
        if any(x in low for x in ("هفته بعد", "هفتهٔ بعد", "next week")): return (today+timedelta(days=7)).isoformat()
        match=re.search(r"(?<!\d)(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-2]?\d|3[01])(?!\d)",text)
        if match:
            try:return date(int(match[1]),int(match[2]),int(match[3])).isoformat()
            except ValueError:pass
        return ""

    def sentence_title(text):
        first=next((line.strip() for line in text.splitlines() if line.strip()), text.strip())
        first=re.split(r"[.!؟\n]",first)[0].strip()
        return (first or "ورودی جدید")[:180]

    def subject_title(text):
        """Extract a useful human subject from a transcript without losing raw text."""
        value=clean(text,20000).strip()
        patterns=(
            r"(?:موضوع(?:s+این)?(?:s+است)?|عنوان(?:s+این)?(?:s+است)?)[\s:：،,-]*(.+)",
            r"(?:درباره(?:ٔ|ی)?|در مورد|مربوط به|برای پروژه(?:ٔ|ی)?)[\s:：،,-]*(.+)",
            r"(?:یادت باشد|به خاطر بسپار|ثبت کن که|این را نگه دار)[\s:：،,-]*(.+)",
        )
        for pattern in patterns:
            match=re.search(pattern,value,re.IGNORECASE)
            if match:
                candidate=re.split(r"[.!؟\n]",match.group(1).strip())[0].strip()
                candidate=re.sub(r"^(که|اینکه|این)‌?\s+",'',candidate,flags=re.IGNORECASE).strip(' ،:؛-')
                if len(candidate)>=3:return candidate[:180]
        first=sentence_title(value)
        first=re.sub(r"^(لطفاً|لطفا|می‌خواهم|میخوام|می خواهم|باید|لازم است)\s+",'',first,flags=re.IGNORECASE).strip()
        return first[:180] or "ورودی جدید"

    def init_schema():
        with db() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS personal_suggestions(
              id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, kind TEXT NOT NULL,
              title TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', confidence INTEGER NOT NULL DEFAULT 50,
              status TEXT NOT NULL DEFAULT 'pending', result_type TEXT NOT NULL DEFAULT '', result_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT '',
              UNIQUE(capture_id,kind,title)
            );
            CREATE INDEX IF NOT EXISTS idx_personal_suggestions_status ON personal_suggestions(status,created_at DESC);
            CREATE TABLE IF NOT EXISTS personal_commitments(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
              direction TEXT NOT NULL DEFAULT 'mine', person_id TEXT NOT NULL DEFAULT '', project_id TEXT NOT NULL DEFAULT '',
              source_capture_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
              due_at TEXT NOT NULL DEFAULT '', follow_up_at TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
              completed_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_personal_commitments_open ON personal_commitments(status,due_at,follow_up_at);
            CREATE TABLE IF NOT EXISTS personal_decisions(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
              alternatives TEXT NOT NULL DEFAULT '', project_id TEXT NOT NULL DEFAULT '', source_capture_id TEXT NOT NULL DEFAULT '',
              review_at TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_personal_decisions_review ON personal_decisions(status,review_at);
            CREATE TABLE IF NOT EXISTS personal_calendar(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'event',
              starts_at TEXT NOT NULL, ends_at TEXT NOT NULL DEFAULT '', reminder_at TEXT NOT NULL DEFAULT '',
              project_id TEXT NOT NULL DEFAULT '', source_capture_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'scheduled',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_personal_calendar_start ON personal_calendar(status,starts_at);
            CREATE TABLE IF NOT EXISTS personal_reviews(
              id TEXT PRIMARY KEY, review_date TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(review_date,kind)
            );
            CREATE TABLE IF NOT EXISTS personal_transcripts(
              voice_id TEXT PRIMARY KEY, transcript TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'fa',
              status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '', capture_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS personal_settings_v2(
              key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS personal_dependencies(
              id TEXT PRIMARY KEY, blocker_type TEXT NOT NULL, blocker_id TEXT NOT NULL,
              blocked_type TEXT NOT NULL, blocked_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'blocks',
              created_at TEXT NOT NULL, UNIQUE(blocker_type,blocker_id,blocked_type,blocked_id)
            );
            """)
            pending_capture_ids=[row['id'] for row in con.execute("SELECT id FROM personal_captures WHERE status='captured' ORDER BY created_at DESC LIMIT 500")]
        for capture_id in pending_capture_ids:
            analyze_capture(capture_id)

    def suggestion(con,capture_id,kind,title,payload,confidence):
        con.execute("""INSERT OR IGNORE INTO personal_suggestions
          (id,capture_id,kind,title,payload,confidence,status,created_at)
          VALUES(?,?,?,?,?,?,'pending',?)""",
          (str(uuid.uuid4()),capture_id,kind,clean(title,220),jd(payload),max(1,min(int(confidence),99)),stamp()))

    def analyze_capture(capture_id):
        with db() as con:
            cap=con.execute("SELECT * FROM personal_captures WHERE id=?",(capture_id,)).fetchone()
            if not cap:return
            text=cap['raw_text']; low=text.casefold(); title=subject_title(text)
            due=parse_relative_date(text)
            project_id=cap['project_id'] if 'project_id' in cap.keys() else ''
            common={'details':text,'project_id':project_id,'source_capture_id':capture_id}

            if any(x in low for x in ('پیگیری','یادآوری','جواب بده','پاسخ بده','تماس بگیر','باید','لازم است','قرار شد')):
                suggestion(con,capture_id,'task',title,{**common,'item_type':'task','status':'inbox','due_at':due},82 if due else 72)
            if any(x in low for x in ('منتظر','قرار شد','قول داد','جواب بدهد','پاسخ بدهد','بررسی کند','ارسال کند')):
                suggestion(con,capture_id,'commitment',title,{**common,'direction':'theirs','status':'waiting','due_at':due,'follow_up_at':due},83)
            if any(x in low for x in ('قول دادم','متعهد شدم','انجام می‌دهم','میفرستم','می‌فرستم','پاسخ می‌دهم')):
                suggestion(con,capture_id,'commitment',title,{**common,'direction':'mine','status':'open','due_at':due},86)
            if any(x in low for x in ('تصمیم گرفتم','تصمیم شد','انتخاب کردم','قرار نهایی','نتیجه این شد')):
                suggestion(con,capture_id,'decision',title,{**common,'decision':text,'review_at':''},88)
            if any(x in low for x in ('به خاطر بسپار','یادت باشد','یاد بگیر','اطلاعات مهم','واقعیت این است','فکت','ثبت کن که','این را نگه دار')):
                suggestion(con,capture_id,'fact',title,{**common,'fact_type':'personal','status':'active'},86)
            if due and any(x in low for x in ('جلسه','قرار ملاقات','وقت','پرواز','مصاحبه','دادگاه','appointment','meeting')):
                suggestion(con,capture_id,'event',title,{**common,'starts_at':due+'T09:00:00+03:30','kind':'event'},80)
            if due and any(x in low for x in ('انقضا','تمدید','مهلت','deadline','expires')):
                suggestion(con,capture_id,'event','موعد: '+title,{**common,'starts_at':due+'T09:00:00+03:30','kind':'deadline'},90)
            if low.startswith('ایمیل:') or '\nفرستنده:' in low:
                if any(x in low for x in ('please reply','لطفاً پاسخ','جواب','پاسخ','مهلت','deadline')):
                    suggestion(con,capture_id,'task','پاسخ به '+title,{**common,'item_type':'email','status':'inbox','due_at':due},88)
            for prefix in ('آقای ','خانم ','دکتر ','مهندس '):
                pos=text.find(prefix)
                if pos>=0:
                    name=re.split(r"[،,.؛;:\n]",text[pos:pos+90])[0].strip()
                    if 3<len(name)<80:suggestion(con,capture_id,'person','شخص: '+name,{'name':name,'kind':'person','capture_id':capture_id},68)

            # A Capture with no actionable signal still receives a review hint; no automatic conversion occurs.
            pending=con.execute("SELECT count(*) FROM personal_suggestions WHERE capture_id=? AND status='pending'",(capture_id,)).fetchone()[0]
            if not pending:
                suggestion(con,capture_id,'note',title,{**common,'item_type':'note','status':'inbox'},45)

    def create_commitment(payload):
        title=clean(payload.get('title'),240)
        if not title:raise HTTPException(400,'عنوان تعهد لازم است')
        direction=clean(payload.get('direction') or 'mine',20)
        status=clean(payload.get('status') or ('waiting' if direction=='theirs' else 'open'),20)
        if direction not in ('mine','theirs'):raise HTTPException(400,'جهت تعهد نامعتبر است')
        if status not in ('open','waiting','done','cancelled'):raise HTTPException(400,'وضعیت تعهد نامعتبر است')
        item={
          'id':str(uuid.uuid4()),'title':title,'details':clean(payload.get('details')),
          'direction':direction,'person_id':clean(payload.get('person_id'),80),'project_id':clean(payload.get('project_id'),80),
          'source_capture_id':clean(payload.get('source_capture_id'),80),'status':status,
          'due_at':clean(payload.get('due_at'),40),'follow_up_at':clean(payload.get('follow_up_at'),40),
          'next_action':clean(payload.get('next_action'),500),'completed_at':stamp() if status=='done' else '',
          'created_at':stamp(),'updated_at':stamp()}
        with db() as con:
            con.execute("""INSERT INTO personal_commitments(id,title,details,direction,person_id,project_id,source_capture_id,status,due_at,follow_up_at,next_action,completed_at,created_at,updated_at)
              VALUES(:id,:title,:details,:direction,:person_id,:project_id,:source_capture_id,:status,:due_at,:follow_up_at,:next_action,:completed_at,:created_at,:updated_at)""",item)
        return item

    def create_decision(payload):
        title=clean(payload.get('title'),240); decision=clean(payload.get('decision'))
        if not title or not decision:raise HTTPException(400,'عنوان و متن تصمیم لازم است')
        item={'id':str(uuid.uuid4()),'title':title,'decision':decision,'reason':clean(payload.get('reason')),
              'alternatives':clean(payload.get('alternatives')),'project_id':clean(payload.get('project_id'),80),
              'source_capture_id':clean(payload.get('source_capture_id'),80),'review_at':clean(payload.get('review_at'),40),
              'status':'active','created_at':stamp(),'updated_at':stamp()}
        with db() as con:
            con.execute("""INSERT INTO personal_decisions(id,title,decision,reason,alternatives,project_id,source_capture_id,review_at,status,created_at,updated_at)
              VALUES(:id,:title,:decision,:reason,:alternatives,:project_id,:source_capture_id,:review_at,:status,:created_at,:updated_at)""",item)
        return item

    def create_event(payload):
        title=clean(payload.get('title'),240); starts=clean(payload.get('starts_at'),40)
        if not title or not starts:raise HTTPException(400,'عنوان و زمان رویداد لازم است')
        try:datetime.fromisoformat(starts.replace('Z','+00:00'))
        except ValueError:raise HTTPException(400,'زمان رویداد نامعتبر است')
        item={'id':str(uuid.uuid4()),'title':title,'details':clean(payload.get('details')),'kind':clean(payload.get('kind') or 'event',30),
              'starts_at':starts,'ends_at':clean(payload.get('ends_at'),40),'reminder_at':clean(payload.get('reminder_at'),40),
              'project_id':clean(payload.get('project_id'),80),'source_capture_id':clean(payload.get('source_capture_id'),80),
              'status':'scheduled','created_at':stamp(),'updated_at':stamp()}
        with db() as con:
            con.execute("""INSERT INTO personal_calendar(id,title,details,kind,starts_at,ends_at,reminder_at,project_id,source_capture_id,status,created_at,updated_at)
              VALUES(:id,:title,:details,:kind,:starts_at,:ends_at,:reminder_at,:project_id,:source_capture_id,:status,:created_at,:updated_at)""",item)
        return item

    @app.get('/api/personal/v2/suggestions')
    def suggestions(status:str='pending',capture_id:str=''):
        if status not in ('pending','accepted','rejected','all'):raise HTTPException(400,'وضعیت نامعتبر است')
        where=[];args=[]
        if status!='all':where.append('s.status=?');args.append(status)
        if capture_id:where.append('s.capture_id=?');args.append(capture_id)
        sql="""SELECT s.*,c.raw_text,c.project_id FROM personal_suggestions s
          LEFT JOIN personal_captures c ON c.id=s.capture_id"""
        if where:sql+=' WHERE '+' AND '.join(where)
        sql+=' ORDER BY s.created_at DESC LIMIT 300'
        with db() as con:rows=[dict(x) for x in con.execute(sql,args)]
        for row in rows:row['payload']=jload(row['payload'])
        return {'items':rows,'count':len(rows)}

    @app.post('/api/personal/v2/analyze/{capture_id}')
    def analyze_again(capture_id:str):
        analyze_capture(capture_id)
        return suggestions(capture_id=capture_id)

    @app.post('/api/personal/v2/suggestions/{sid}/decide')
    def decide_suggestion(sid:str,payload:dict=Body(...)):
        action=clean(payload.get('action'),20)
        if action not in ('accept','reject'):raise HTTPException(400,'تصمیم نامعتبر است')
        with db() as con:
            row=con.execute("SELECT * FROM personal_suggestions WHERE id=?",(sid,)).fetchone()
            if not row:raise HTTPException(404)
            if row['status']!='pending':return {'ok':True,'already_decided':True,'status':row['status']}
        if action=='reject':
            with db() as con:con.execute("UPDATE personal_suggestions SET status='rejected',decided_at=? WHERE id=?",(stamp(),sid))
            return {'ok':True,'status':'rejected'}
        data=jload(row['payload']); kind=row['kind']; result_type=kind; result_id=''
        override=payload.get('data') if isinstance(payload.get('data'),dict) else {}
        data.update(override);data.setdefault('title',row['title'])
        if kind in ('task','note'):
            result=item_fn(data)['item'];result_type='item';result_id=result['id']
        elif kind=='fact':
            result=fact_fn(data)['fact'];result_type='fact';result_id=result['id']
        elif kind=='commitment':
            result=create_commitment(data);result_id=result['id']
        elif kind=='decision':
            result=create_decision(data);result_id=result['id']
        elif kind=='event':
            result=create_event(data);result_id=result['id']
        elif kind=='person':
            name=clean(data.get('name'),160)
            with db() as con:
                existing=con.execute("SELECT * FROM entities WHERE name=? COLLATE NOCASE AND kind='person'",(name,)).fetchone()
                if existing:result=dict(existing)
                else:
                    result={'id':str(uuid.uuid4()),'name':name,'kind':'person','country':'','notes':'','created_at':stamp(),'updated_at':stamp()}
                    con.execute("INSERT INTO entities(id,name,kind,country,notes,created_at,updated_at) VALUES(:id,:name,:kind,:country,:notes,:created_at,:updated_at)",result)
            result_id=result['id']
        else:
            result=item_fn({'title':row['title'],'details':data.get('details',''),'item_type':'note','status':'inbox','project_id':data.get('project_id',''),'source':'capture_suggestion'})['item'];result_type='item';result_id=result['id']
        with db() as con:
            con.execute("UPDATE personal_suggestions SET status='accepted',result_type=?,result_id=?,decided_at=? WHERE id=?",(result_type,result_id,stamp(),sid))
            con.execute("INSERT INTO personal_events(id,subject_type,subject_id,action,details,created_at) VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),result_type,result_id,'suggestion_accepted',row['title'],stamp()))
        return {'ok':True,'status':'accepted','result_type':result_type,'result':result}

    @app.get('/api/personal/v2/commitments')
    def commitments(status:str='open'):
        where="WHERE status IN ('open','waiting')" if status=='open' else ("" if status=='all' else "WHERE status=?")
        args=[] if status in ('open','all') else [status]
        with db() as con:rows=[dict(x) for x in con.execute('SELECT * FROM personal_commitments '+where+' ORDER BY CASE WHEN due_at="" THEN 1 ELSE 0 END,due_at,updated_at DESC',args)]
        return {'items':rows,'count':len(rows)}

    @app.post('/api/personal/v2/commitments')
    def add_commitment(payload:dict=Body(...)):
        return {'ok':True,'item':create_commitment(payload)}

    @app.patch('/api/personal/v2/commitments/{cid}')
    def patch_commitment(cid:str,payload:dict=Body(...)):
        allowed={'title','details','direction','person_id','project_id','status','due_at','follow_up_at','next_action'}
        with db() as con:
            current=con.execute('SELECT * FROM personal_commitments WHERE id=?',(cid,)).fetchone()
            if not current:raise HTTPException(404)
            updates=[];args=[]
            for key,value in payload.items():
                if key not in allowed:continue
                value=clean(value,4000 if key=='details' else 500)
                if key=='status' and value not in ('open','waiting','done','cancelled'):raise HTTPException(400,'وضعیت نامعتبر است')
                updates.append(key+'=?');args.append(value)
            if payload.get('status')=='done':updates.append('completed_at=?');args.append(stamp())
            if updates:
                updates.append('updated_at=?');args.extend([stamp(),cid]);con.execute('UPDATE personal_commitments SET '+','.join(updates)+' WHERE id=?',args)
            row=con.execute('SELECT * FROM personal_commitments WHERE id=?',(cid,)).fetchone()
        return {'ok':True,'item':dict(row)}

    @app.get('/api/personal/v2/decisions')
    def decisions(status:str='active'):
        with db() as con:
            rows=[dict(x) for x in con.execute('SELECT * FROM personal_decisions'+('' if status=='all' else ' WHERE status=?')+' ORDER BY updated_at DESC',() if status=='all' else (status,))]
        return {'items':rows,'count':len(rows)}

    @app.post('/api/personal/v2/decisions')
    def add_decision(payload:dict=Body(...)):
        return {'ok':True,'item':create_decision(payload)}

    @app.get('/api/personal/v2/calendar')
    def calendar(days:int=60):
        start=local_today().isoformat();end=(local_today()+timedelta(days=max(1,min(days,365)))).isoformat()
        with db() as con:
            rows=[dict(x) for x in con.execute("SELECT * FROM personal_calendar WHERE status='scheduled' AND substr(starts_at,1,10) BETWEEN ? AND ? ORDER BY starts_at",(start,end))]
        return {'items':rows,'count':len(rows)}

    @app.post('/api/personal/v2/calendar')
    def add_calendar(payload:dict=Body(...)):
        return {'ok':True,'item':create_event(payload)}

    def calendar_setting():
        with db() as con:
            row=con.execute("SELECT value FROM personal_settings_v2 WHERE key='calendar_ics_url'").fetchone()
        return row['value'] if row else ''

    @app.get('/api/personal/v2/calendar/config')
    def calendar_config():
        url=calendar_setting();return {'configured':bool(url),'url':url}

    @app.post('/api/personal/v2/calendar/config')
    def save_calendar_config(payload:dict=Body(...)):
        url=clean(payload.get('url'),1000)
        if url:
            parsed=urllib.parse.urlparse(url)
            if parsed.scheme!='https' or not parsed.hostname:raise HTTPException(400,'لینک تقویم باید HTTPS باشد')
            allowed=('.google.com','.googleusercontent.com','.icloud.com','.apple.com')
            if not (parsed.hostname=='google.com' or parsed.hostname=='icloud.com' or parsed.hostname=='apple.com' or parsed.hostname.endswith(allowed)):
                raise HTTPException(400,'برای جلوگیری از دسترسی ناامن، فقط لینک تقویم Google یا Apple پذیرفته می‌شود')
        with db() as con:
            if url:con.execute("INSERT INTO personal_settings_v2(key,value,updated_at) VALUES('calendar_ics_url',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(url,stamp()))
            else:con.execute("DELETE FROM personal_settings_v2 WHERE key='calendar_ics_url'")
        return {'ok':True,'configured':bool(url)}

    def parse_ics(text):
        text=text.replace('\r\n','\n').replace('\r','\n')
        unfolded=re.sub(r'\n[ \t]','',text)
        events=[]
        for block in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT',unfolded,re.S|re.I):
            values={}
            for line in block.split('\n'):
                if ':' not in line:continue
                key,value=line.split(':',1);key=key.split(';',1)[0].upper();values[key]=value.strip()
            uid=values.get('UID');summary=values.get('SUMMARY');start=values.get('DTSTART')
            if not uid or not summary or not start:continue
            match=re.match(r'(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2}))?',start)
            if not match:continue
            y,mo,day,hh,mm,ss=match.groups();iso=f'{y}-{mo}-{day}T{hh or "09"}:{mm or "00"}:{ss or "00"}+03:30'
            events.append((uid,summary,iso,values.get('DESCRIPTION','')))
        return events

    @app.post('/api/personal/v2/calendar/sync')
    def sync_calendar():
        url=calendar_setting()
        if not url:raise HTTPException(400,'ابتدا لینک تقویم را ثبت کن')
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'HosseinArchive/5.0'})
            with urllib.request.urlopen(request,timeout=20) as response:content=response.read(2_000_000).decode('utf-8','replace')
            events=parse_ics(content)
        except Exception:raise HTTPException(502,'دریافت تقویم موفق نبود')
        imported=0
        with db() as con:
            for uid,title,starts,details in events:
                source_id='ics:'+hashlib.sha256(uid.encode()).hexdigest()[:32]
                existing=con.execute("SELECT id FROM personal_calendar WHERE source_capture_id=?",(source_id,)).fetchone()
                if existing:
                    con.execute("UPDATE personal_calendar SET title=?,details=?,starts_at=?,updated_at=? WHERE id=?",(title,details,starts,stamp(),existing['id']))
                else:
                    con.execute("INSERT INTO personal_calendar(id,title,details,kind,starts_at,source_capture_id,status,created_at,updated_at) VALUES(?,?,?,'external',?,?,'scheduled',?,?)",(str(uuid.uuid4()),title,details,starts,source_id,stamp(),stamp()));imported+=1
        return {'ok':True,'imported':imported,'total':len(events)}

    @app.get('/api/personal/v2/dependencies')
    def dependencies(blocked_id:str=''):
        sql='SELECT * FROM personal_dependencies';args=[]
        if blocked_id:sql+=' WHERE blocked_id=?';args=[blocked_id]
        with db() as con:rows=[dict(x) for x in con.execute(sql+' ORDER BY created_at DESC',args)]
        return {'items':rows,'count':len(rows)}

    @app.post('/api/personal/v2/dependencies')
    def add_dependency(payload:dict=Body(...)):
        values={k:clean(payload.get(k),80) for k in ('blocker_type','blocker_id','blocked_type','blocked_id')}
        if not all(values.values()):raise HTTPException(400,'دو طرف وابستگی لازم است')
        if values['blocker_type']==values['blocked_type'] and values['blocker_id']==values['blocked_id']:raise HTTPException(400,'یک مورد نمی‌تواند خودش را مسدود کند')
        item={'id':str(uuid.uuid4()),**values,'relation':clean(payload.get('relation') or 'blocks',40),'created_at':stamp()}
        with db() as con:con.execute('INSERT OR IGNORE INTO personal_dependencies VALUES(:id,:blocker_type,:blocker_id,:blocked_type,:blocked_id,:relation,:created_at)',item)
        return {'ok':True,'item':item}

    @app.delete('/api/personal/v2/dependencies/{dependency_id}')
    def delete_dependency(dependency_id:str):
        with db() as con:changed=con.execute('DELETE FROM personal_dependencies WHERE id=?',(dependency_id,)).rowcount
        if not changed:raise HTTPException(404)
        return {'ok':True}

    @app.get('/api/personal/v2/people')
    def people(q:str=''):
        term='%'+q.strip()+'%'
        with db() as con:
            rows=[dict(x) for x in con.execute("""SELECT e.*,
              (SELECT count(*) FROM personal_facts f WHERE f.entity_id=e.id AND f.status='active') facts,
              (SELECT count(*) FROM documents d WHERE d.entity_id=e.id AND d.deleted=0) documents,
              (SELECT count(*) FROM personal_commitments c WHERE c.person_id=e.id AND c.status IN ('open','waiting')) open_commitments
              FROM entities e WHERE e.kind='person' AND (?='%%' OR e.name LIKE ?) ORDER BY e.updated_at DESC""",(term,term))]
        return {'items':rows,'count':len(rows)}

    @app.get('/api/personal/v2/people/{pid}')
    def person_dossier(pid:str):
        with db() as con:
            person=con.execute("SELECT * FROM entities WHERE id=? AND kind='person'",(pid,)).fetchone()
            if not person:raise HTTPException(404)
            facts=[dict(x) for x in con.execute("SELECT * FROM personal_facts WHERE entity_id=? ORDER BY updated_at DESC",(pid,))]
            docs=[dict(x) for x in con.execute("SELECT id,title,document_type,expiry_date,updated_at FROM documents WHERE entity_id=? AND deleted=0 ORDER BY updated_at DESC",(pid,))]
            commits=[dict(x) for x in con.execute("SELECT * FROM personal_commitments WHERE person_id=? ORDER BY updated_at DESC",(pid,))]
            name=person['name'];term='%'+name+'%'
            mentions=[dict(x) for x in con.execute("SELECT id,raw_text,source,created_at FROM personal_captures WHERE raw_text LIKE ? ORDER BY created_at DESC LIMIT 50",(term,))]
        return {'person':dict(person),'facts':facts,'documents':docs,'commitments':commits,'mentions':mentions}

    def risk_rows():
        today=local_today().isoformat();stale=(local_today()-timedelta(days=7)).isoformat();capture_stale=(local_today()-timedelta(days=3)).isoformat()
        risks=[]
        with db() as con:
            for x in con.execute("SELECT id,title,due_at,project_id FROM personal_items WHERE "+OPEN_ITEM+" AND due_at<>'' AND substr(due_at,1,10)<? ORDER BY due_at LIMIT 50",(today,)):
                risks.append({'level':'high','kind':'overdue','title':x['title'],'detail':'موعد '+x['due_at'][:10]+' گذشته است','target_type':'item','target_id':x['id']})
            for x in con.execute("SELECT id,title,follow_up_at FROM personal_items WHERE status='waiting' AND (follow_up_at='' OR substr(follow_up_at,1,10)<=?) ORDER BY updated_at LIMIT 50",(today,)):
                risks.append({'level':'medium','kind':'waiting','title':x['title'],'detail':'منتظر پاسخ و آماده پیگیری','target_type':'item','target_id':x['id']})
            for x in con.execute("SELECT id,title,due_at FROM personal_commitments WHERE status IN ('open','waiting') AND due_at<>'' AND substr(due_at,1,10)<? ORDER BY due_at LIMIT 50",(today,)):
                risks.append({'level':'high','kind':'commitment','title':x['title'],'detail':'تعهد از موعد گذشته','target_type':'commitment','target_id':x['id']})
            for x in con.execute("SELECT id,title,review_at FROM personal_decisions WHERE status='active' AND review_at<>'' AND substr(review_at,1,10)<=?",(today,)):
                risks.append({'level':'medium','kind':'decision_review','title':x['title'],'detail':'زمان بازبینی تصمیم رسیده است','target_type':'decision','target_id':x['id']})
            for x in con.execute("SELECT id,title,expiry_date FROM documents WHERE deleted=0 AND expiry_date<>'' AND expiry_date BETWEEN ? AND ?",(today,(local_today()+timedelta(days=60)).isoformat())):
                risks.append({'level':'medium','kind':'expiry','title':x['title'],'detail':'انقضا در '+x['expiry_date'],'target_type':'document','target_id':x['id']})
            for x in con.execute("SELECT id,suggested_title,created_at FROM personal_captures WHERE status='captured' AND substr(created_at,1,10)<=?",(capture_stale,)):
                risks.append({'level':'low','kind':'unreviewed','title':x['suggested_title'] or 'Capture بررسی‌نشده','detail':'بیش از سه روز بدون تصمیم','target_type':'capture','target_id':x['id']})
            for x in con.execute("SELECT id,title,updated_at FROM personal_projects WHERE status='active' AND substr(updated_at,1,10)<=?",((local_today()-timedelta(days=14)).isoformat(),)):
                risks.append({'level':'low','kind':'stale_project','title':x['title'],'detail':'پروژه بیش از ۱۴ روز بدون حرکت','target_type':'project','target_id':x['id']})
        order={'high':0,'medium':1,'low':2};risks.sort(key=lambda x:order[x['level']])
        return risks

    @app.get('/api/personal/v2/risks')
    def risks():
        items=risk_rows();return {'items':items,'count':len(items),'high':sum(x['level']=='high' for x in items)}

    @app.get('/api/personal/v2/brief')
    def brief():
        today=local_today().isoformat();week=(local_today()+timedelta(days=7)).isoformat()
        with db() as con:
            focus_sql="""SELECT id,title,status,priority,due_at,follow_up_at,project_id FROM personal_items
              WHERE status NOT IN ('done','archived') AND (status='today' OR (due_at<>'' AND substr(due_at,1,10)<=?))
              ORDER BY CASE WHEN due_at<>'' AND substr(due_at,1,10)<? THEN 0 ELSE 1 END,priority DESC,due_at LIMIT 3"""
            focus=[dict(x) for x in con.execute(focus_sql,(today,today))]
            upcoming=con.execute("SELECT count(*) FROM personal_calendar WHERE status='scheduled' AND substr(starts_at,1,10) BETWEEN ? AND ?",(today,week)).fetchone()[0]
            emails=con.execute("SELECT count(*) FROM personal_captures WHERE status='captured' AND source='imap'").fetchone()[0]
            pending=con.execute("SELECT count(*) FROM personal_suggestions WHERE status='pending'").fetchone()[0]
            waiting=con.execute("SELECT count(*) FROM personal_commitments WHERE status='waiting'").fetchone()[0]
        risk=risk_rows()
        return {'date':today,'focus':focus,'risks':risk[:5],'counts':{'pending_suggestions':pending,'email_captures':emails,'waiting_commitments':waiting,'upcoming_events':upcoming,'risks':len(risk)},
                'message':'امروز '+str(len(focus))+' اولویت اصلی و '+str(len(risk))+' موضوع نیازمند توجه داری.'}

    @app.get('/api/personal/v2/timeline')
    def timeline(limit:int=100):
        limit=max(10,min(limit,500))
        union="""
          SELECT 'capture' kind,id,coalesce(suggested_title,substr(raw_text,1,120)) title,source detail,created_at FROM personal_captures
          UNION ALL SELECT 'item',id,title,status,updated_at FROM personal_items
          UNION ALL SELECT 'fact',id,label,fact_type,updated_at FROM personal_facts
          UNION ALL SELECT 'commitment',id,title,status,updated_at FROM personal_commitments
          UNION ALL SELECT 'decision',id,title,status,updated_at FROM personal_decisions
          UNION ALL SELECT 'event',id,title,kind,updated_at FROM personal_calendar
          UNION ALL SELECT 'document',id,title,document_type,updated_at FROM documents WHERE deleted=0
        """
        with db() as con:rows=[dict(x) for x in con.execute('SELECT * FROM ('+union+') ORDER BY created_at DESC LIMIT ?',(limit,))]
        return {'items':rows,'count':len(rows)}

    @app.get('/api/personal/v2/memory')
    def memory(q:str=Query(min_length=2,max_length=200)):
        term='%'+q.strip()+'%';results=[]
        with db() as con:
            queries=[
              ('fact',"SELECT id,label title,value detail,updated_at at FROM personal_facts WHERE status='active' AND (label LIKE ? OR value LIKE ? OR details LIKE ?) ORDER BY updated_at DESC LIMIT 15",(term,term,term)),
              ('capture',"SELECT id,suggested_title title,raw_text detail,created_at at FROM personal_captures WHERE raw_text LIKE ? ORDER BY created_at DESC LIMIT 15",(term,)),
              ('item',"SELECT id,title,details detail,updated_at at FROM personal_items WHERE title LIKE ? OR details LIKE ? ORDER BY updated_at DESC LIMIT 15",(term,term)),
              ('decision',"SELECT id,title,decision||CASE WHEN reason<>'' THEN ' · دلیل: '||reason ELSE '' END detail,updated_at at FROM personal_decisions WHERE title LIKE ? OR decision LIKE ? OR reason LIKE ? ORDER BY updated_at DESC LIMIT 15",(term,term,term)),
              ('commitment',"SELECT id,title,details||' · وضعیت: '||status detail,updated_at at FROM personal_commitments WHERE title LIKE ? OR details LIKE ? ORDER BY updated_at DESC LIMIT 15",(term,term)),
              ('document',"SELECT id,title,substr(ocr_text,1,900) detail,updated_at at FROM documents WHERE deleted=0 AND (title LIKE ? OR original_name LIKE ? OR ocr_text LIKE ?) ORDER BY updated_at DESC LIMIT 15",(term,term,term)),
            ]
            for kind,sql,args in queries:
                for row in con.execute(sql,args):
                    item=dict(row);item['kind']=kind;item['detail']=clean(item.get('detail'),900);results.append(item)
        results.sort(key=lambda x:x.get('at') or '',reverse=True);results=results[:40]
        answer='مدرک کافی پیدا نشد.' if not results else 'بر اساس '+str(len(results))+' منبع ثبت‌شده، مرتبط‌ترین موارد در پایین آمده‌اند.'
        return {'query':q,'answer':answer,'sources':results,'count':len(results)}

    @app.get('/api/personal/v2/reviews/{kind}')
    def get_review(kind:str,review_date:str=''):
        if kind not in ('morning','evening'):raise HTTPException(400)
        day=review_date or local_today().isoformat()
        with db() as con:row=con.execute('SELECT * FROM personal_reviews WHERE review_date=? AND kind=?',(day,kind)).fetchone()
        item=dict(row) if row else {'review_date':day,'kind':kind,'content':{}}
        if row:item['content']=jload(item['content'])
        return {'item':item}

    @app.post('/api/personal/v2/reviews/{kind}')
    def save_review(kind:str,payload:dict=Body(...)):
        if kind not in ('morning','evening'):raise HTTPException(400)
        day=clean(payload.get('review_date') or local_today().isoformat(),10);content=payload.get('content') if isinstance(payload.get('content'),dict) else payload
        with db() as con:
            existing=con.execute('SELECT id FROM personal_reviews WHERE review_date=? AND kind=?',(day,kind)).fetchone()
            if existing:con.execute('UPDATE personal_reviews SET content=?,updated_at=? WHERE id=?',(jd(content),stamp(),existing['id']));rid=existing['id']
            else:rid=str(uuid.uuid4());con.execute('INSERT INTO personal_reviews VALUES(?,?,?,?,?,?)',(rid,day,kind,jd(content),stamp(),stamp()))
        return {'ok':True,'id':rid}

    @app.post('/api/personal/v2/voice/{voice_id}/transcribe')
    def transcribe_voice(voice_id:str,request:Request):
        with db() as con:voice=con.execute('SELECT * FROM personal_voice WHERE id=?',(voice_id,)).fetchone()
        if not voice:raise HTTPException(404)
        command=os.getenv('WHISPER_CMD','').strip()
        if not command:
            with db() as con:con.execute("INSERT OR REPLACE INTO personal_transcripts(voice_id,status,error,created_at,updated_at) VALUES(?,'unavailable',?,?,?)",(voice_id,'موتور گفتار به متن نصب نشده است',stamp(),stamp()))
            raise HTTPException(503,'موتور گفتار به متن هنوز روی سرور نصب نشده است؛ فایل صوتی محفوظ است.')
        audio=root/'personal-private'/'voice'/voice_id
        try:
            proc=subprocess.run([*shlex.split(command),str(audio)],capture_output=True,text=True,timeout=600,check=True)
            transcript=clean(proc.stdout,20000)
            if not transcript:raise ValueError('empty transcript')
            cap=capture_fn({'text':transcript,'source':'voice_transcript'})['capture']
            with db() as con:con.execute("INSERT OR REPLACE INTO personal_transcripts(voice_id,transcript,language,status,error,capture_id,created_at,updated_at) VALUES(?,?,'fa','done','',?,?,?)",(voice_id,transcript,cap['id'],stamp(),stamp()))
            return {'ok':True,'transcript':transcript,'capture':cap}
        except subprocess.TimeoutExpired:raise HTTPException(504,'تبدیل صوت بیش از حد طول کشید')
        except Exception:
            raise HTTPException(502,'تبدیل صوت ناموفق بود؛ فایل اصلی محفوظ است.')

    @app.get('/api/personal/v2/export')
    def export_personal():
        tables=['personal_projects','personal_captures','personal_suggestions','personal_items','personal_facts','personal_fact_events','personal_cases','personal_commitments','personal_decisions','personal_calendar','personal_reviews','personal_links','personal_events']
        payload={'exported_at':stamp(),'schema':'hossein-personal-v2','tables':{}}
        with db() as con:
            for table in tables:
                try:payload['tables'][table]=[dict(x) for x in con.execute('SELECT * FROM '+table)]
                except Exception:payload['tables'][table]=[]
        response=JSONResponse(payload)
        response.headers['Content-Disposition']='attachment; filename="hossein-personal-export.json"'
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/personal/v2/system')
    def system_health():
        with db() as con:
            integrity=con.execute('PRAGMA quick_check').fetchone()[0]
            counts={table:con.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('personal_captures','personal_items','personal_facts','personal_commitments','personal_decisions','personal_calendar','personal_suggestions')}
        usage=shutil.disk_usage(root)
        return {'status':'ok' if integrity=='ok' else 'degraded','database_integrity':integrity,'counts':counts,
                'storage':{'total':usage.total,'used':usage.used,'free':usage.free},
                'speech_to_text':{'configured':bool(os.getenv('WHISPER_CMD','').strip()),'command':bool(os.getenv('WHISPER_CMD','').strip())},'time':stamp()}

    @app.get('/personal/v2.js')
    def v2_javascript():
        return FileResponse(web/'personal-v2.js',media_type='application/javascript',headers={'Cache-Control':'no-cache'})

    return init_schema, analyze_capture

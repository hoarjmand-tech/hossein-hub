import os,time,socket,urllib.request
from pathlib import Path
from datetime import datetime,date,timedelta
from sqlalchemy import select
from .core import SessionLocal
from .models import ManagedAsset,CheckResult,SystemAlert,Document,Notification
def sec(p):
 try:return Path(p).read_text().strip()
 except:return ""
TOKEN=sec(os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token"))
ADMIN=sec(os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id"))
PROXY=os.getenv("TELEGRAM_PROXY","socks5h://127.0.0.1:10808")
def tg(msg):
 if not TOKEN or not ADMIN:return
 try:
  import requests
  s=requests.Session();s.proxies.update({"http":PROXY,"https":PROXY})
  s.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",json={"chat_id":ADMIN,"text":msg},timeout=15)
 except Exception as e:print("telegram-alert:",e,flush=True)
def probe(a):
 t=time.monotonic()
 try:
  if a.protocol in ("http","https"):
   url=f"{a.protocol}://{a.address}"+(f":{a.port}" if a.port else "")+"/"
   with urllib.request.urlopen(url,timeout=5) as z:z.read(1)
  else:
   with socket.create_connection((a.address,a.port or 443),timeout=5):pass
  return "up",int((time.monotonic()-t)*1000),"reachable"
 except Exception as e:return "down",None,str(e)[:300]
last_expiry_scan=None
while True:
 try:
  with SessionLocal() as db:
   for a in db.scalars(select(ManagedAsset).where(ManagedAsset.enabled==True)):
    old=a.last_status;st,lat,msg=probe(a);a.last_status=st;a.last_latency_ms=lat
    if st=="up":a.last_seen=datetime.utcnow()
    db.add(CheckResult(asset_id=a.id,status=st,latency_ms=lat,message=msg))
    if old=="up" and st=="down":
     db.add(SystemAlert(asset_id=a.id,severity="critical",title=f"{a.name} در دسترس نیست",body=msg));tg(f"🔴 Hossein Hub\n{a.name} در دسترس نیست\n{a.address}:{a.port or ''}")
    if old=="down" and st=="up":
     db.add(SystemAlert(asset_id=a.id,severity="info",title=f"{a.name} دوباره در دسترس است",body=f"Latency: {lat} ms"));tg(f"🟢 Hossein Hub\n{a.name} دوباره در دسترس است\nLatency: {lat} ms")
   if last_expiry_scan!=date.today():
    end=date.today()+timedelta(days=30)
    docs=list(db.scalars(select(Document).where(Document.deleted==False,Document.expiry_date!=None,Document.expiry_date>=date.today(),Document.expiry_date<=end)))
    for d in docs:
     exists=db.scalar(select(Notification).where(Notification.kind=="expiry",Notification.document_id==d.id,Notification.created_at>=datetime.utcnow()-timedelta(days=1)))
     if not exists:
      days=(d.expiry_date-date.today()).days
      db.add(Notification(kind="expiry",title=f"انقضای {d.title}",body=f"{days} روز تا انقضا — {d.expiry_date}",document_id=d.id))
      tg(f"⏰ Hossein Hub\n{d.title}\n{days} روز تا انقضا ({d.expiry_date})")
    last_expiry_scan=date.today()
   db.commit()
 except Exception as e:print("monitor:",e,flush=True)
 time.sleep(60)

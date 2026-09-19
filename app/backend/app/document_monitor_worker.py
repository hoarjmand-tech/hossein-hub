import os,time
from pathlib import Path
from datetime import date,datetime,timedelta
from sqlalchemy import select
from .core import SessionLocal
from .models import Document,Notification,DocumentSourceState

TOKEN_FILE=os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token")
ADMIN_FILE=os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id")
PROXY=os.getenv("TELEGRAM_PROXY","socks5h://127.0.0.1:10808")

def fsecret(path):
 try:return Path(path).read_text().strip()
 except:return ""

def tg(msg):
 token=fsecret(TOKEN_FILE);admin=fsecret(ADMIN_FILE)
 if not token or not admin:return
 try:
  import requests
  s=requests.Session();s.proxies.update({"http":PROXY,"https":PROXY})
  s.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":admin,"text":msg},timeout=15)
 except Exception as e:print("document-monitor telegram:",e,flush=True)

def expiry_notifications(db):
 today=date.today();created=[]
 for days in (90,30,7,1,0):
  target=today+timedelta(days=days)
  for d in db.scalars(select(Document).where(Document.deleted==False,Document.expiry_date==target)):
   kind=f"document_expiry_{days}"
   exists=db.scalar(select(Notification).where(Notification.kind==kind,Notification.document_id==d.id))
   if exists:continue
   title=("منقضی شده" if days==0 else f"{days} روز تا انقضا")+f": {d.title}"
   body=f"تاریخ انقضا: {d.expiry_date}"
   db.add(Notification(kind=kind,title=title,body=body,document_id=d.id));created.append(title)
 return created

while True:
 try:
  with SessionLocal() as db:
   created=expiry_notifications(db)
   db.commit()
   if created:
    tg("📄 Hossein Hub Documents\n"+"\n".join("• "+x for x in created[:20]))
   for s in db.scalars(select(DocumentSourceState)):
    if s.last_error and s.last_scan_at and s.last_scan_at>=datetime.utcnow()-timedelta(days=1):
     kind="document_source_error_"+s.source
     exists=db.scalar(select(Notification).where(Notification.kind==kind,Notification.created_at>=datetime.utcnow()-timedelta(days=1)))
     if not exists:
      db.add(Notification(kind=kind,title=f"Document source error: {s.source}",body=s.last_error[:1000]))
   db.commit()
 except Exception as e:print("document-monitor:",e,flush=True)
 time.sleep(3600)

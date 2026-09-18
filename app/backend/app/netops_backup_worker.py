import os,json,time,hashlib
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal
from .models import DeviceConfigSnapshot,SystemAlert,Notification,Audit

ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"))
INV=ROOT/"devices.json"
TOKEN_FILE=os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token")
ADMIN_FILE=os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id")
PROXY=os.getenv("TELEGRAM_PROXY","socks5h://127.0.0.1:10808")
INTERVAL=int(os.getenv("NETOPS_BACKUP_INTERVAL","86400"))

def secret(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

def file_secret(path):
 try:return Path(path).read_text().strip()
 except:return ""

def inventory():
 try:
  x=json.loads(INV.read_text())
  return x if isinstance(x,list) else []
 except:return []

def connect(d):
 from netmiko import ConnectHandler
 kw={"device_type":d.get("device_type") or "cisco_ios","host":d["host"],"port":int(d.get("port",22)),
     "username":secret(d.get("username_file","")) or d.get("username",""),"password":secret(d.get("password_file","")),
     "secret":secret(d.get("enable_secret_file","")),"fast_cli":False,"conn_timeout":10,"auth_timeout":12,"banner_timeout":12}
 c=ConnectHandler(**kw)
 if kw["secret"]:
  try:c.enable()
  except:pass
 return c

def backup_command(dtype):
 if "fortinet" in dtype:return "show full-configuration"
 if "mikrotik" in dtype:return "/export terse"
 if "juniper" in dtype:return "show configuration | display set"
 return "show running-config"

def tg(msg):
 token=file_secret(TOKEN_FILE);admin=file_secret(ADMIN_FILE)
 if not token or not admin:return
 try:
  import requests
  s=requests.Session();s.proxies.update({"http":PROXY,"https":PROXY})
  s.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":admin,"text":msg},timeout=15)
 except Exception as e:print("netops-backup-telegram:",e,flush=True)

def backup_one(db,d):
 c=None
 try:
  c=connect(d);cmd=backup_command(d.get("device_type") or "")
  text=c.send_command(cmd,read_timeout=180)
 finally:
  try:
   if c:c.disconnect()
  except:pass

 sha=hashlib.sha256(text.encode()).hexdigest()
 last=db.scalar(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_id==str(d.get("id"))).order_by(DeviceConfigSnapshot.created_at.desc()))
 if last and last.sha256==sha:
  return "unchanged",last.id,len(text.encode())

 s=DeviceConfigSnapshot(device_id=str(d.get("id")),device_name=d.get("name") or d.get("host") or str(d.get("id")),
   config_text=text,sha256=sha,source="scheduled")
 db.add(s);db.flush()
 db.add(Audit(action="netops.backup.scheduled",object_type="network_device",object_id=s.id,detail=s.device_name))
 if last:
  title=f"Config تغییر کرد: {s.device_name}"
  db.add(SystemAlert(severity="warning",title=title,body=f"Snapshot جدید {s.id}"))
  db.add(Notification(kind="config_drift",title=title,body="تغییر کانفیگ نسبت به Snapshot قبلی شناسایی شد."))
  tg(f"⚠️ Hossein Hub\nConfig Drift Detected\n{s.device_name}\n{d.get('host','')}")
  return "changed",s.id,len(text.encode())
 return "created",s.id,len(text.encode())

while True:
 started=datetime.utcnow();ok=0;changed=0;failed=0
 try:
  with SessionLocal() as db:
   for d in inventory():
    if not d.get("enabled",True):continue
    if not d.get("username_file") or not d.get("password_file"):continue
    try:
     status,_,_=backup_one(db,d);ok+=1
     if status=="changed":changed+=1
     db.commit()
    except Exception as e:
     failed+=1
     db.rollback()
     title=f"Backup Config ناموفق: {d.get('name') or d.get('host')}"
     db.add(SystemAlert(severity="warning",title=title,body=str(e)[:500]))
     db.add(Notification(kind="config_backup",title=title,body=str(e)[:500]))
     db.commit()
   if ok or failed:
    tg(f"💾 Hossein Hub NetOps Backup\nSuccess: {ok}\nChanged: {changed}\nFailed: {failed}")
 except Exception as e:print("netops-backup:",e,flush=True)
 elapsed=(datetime.utcnow()-started).total_seconds()
 time.sleep(max(60,INTERVAL-int(elapsed)))

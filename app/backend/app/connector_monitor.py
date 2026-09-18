import os,time,json
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal
from .models import SystemAlert,Notification,ConnectorSample
from .connectors import fortigate_summary,vmware_inventory,veeam_summary

def sec(p):
 try:return Path(p).read_text().strip()
 except:return ""

TOKEN=sec(os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token"))
ADMIN=sec(os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id"))
PROXY=os.getenv("TELEGRAM_PROXY","socks5h://127.0.0.1:10808")
STATE=Path(os.getenv("CONNECTOR_STATE_FILE","/data/connector_state.json"))

def tg(msg):
 if not TOKEN or not ADMIN:return
 try:
  import requests
  s=requests.Session();s.proxies.update({"http":PROXY,"https":PROXY})
  s.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",json={"chat_id":ADMIN,"text":msg},timeout=15)
 except Exception as e:print("connector-telegram:",e,flush=True)

def load_state():
 try:return json.loads(STATE.read_text())
 except:return {}

def save_state(x):
 STATE.parent.mkdir(parents=True,exist_ok=True)
 STATE.write_text(json.dumps(x,ensure_ascii=False))

def check(name,fn):
 try:
  r=fn() or {}
  if not r.get("configured"):return "unconfigured","not configured",{}
  if r.get("ok"):return "up","connected",r.get("data") if isinstance(r.get("data"),dict) else {}
  return "down",str(r.get("error") or "connector error")[:300],{}
 except Exception as e:return "down",str(e)[:300],{}

while True:
 try:
  old=load_state();new={}
  checks={
   "FortiGate":fortigate_summary,
   "ESXi/vCenter":vmware_inventory,
   "Veeam":veeam_summary,
  }
  with SessionLocal() as db:
   for name,fn in checks.items():
    status,msg,detail=check(name,fn);new[name]={"status":status,"at":datetime.utcnow().isoformat()+"Z","message":msg};db.add(ConnectorSample(connector=name,status=status,summary_json=json.dumps(detail,ensure_ascii=False)[:20000]))
    prev=(old.get(name) or {}).get("status")
    if prev and prev!=status and status=="down":
     title=f"{name} Connector قطع شد"
     db.add(SystemAlert(severity="critical",title=title,body=msg))
     db.add(Notification(kind="connector",title=title,body=msg))
     tg(f"🔴 Hossein Hub\n{name} Connector DOWN\n{msg}")
    elif prev=="down" and status=="up":
     title=f"{name} Connector برقرار شد"
     db.add(SystemAlert(severity="info",title=title,body="Connection restored"))
     db.add(Notification(kind="connector",title=title,body="Connection restored"))
     tg(f"🟢 Hossein Hub\n{name} Connector UP")
   db.commit()
  save_state(new)
 except Exception as e:print("connector-monitor:",e,flush=True)
 time.sleep(300)

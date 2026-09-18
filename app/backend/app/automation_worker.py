import os,json,time,socket,urllib.request
from pathlib import Path
from datetime import datetime,timedelta
from sqlalchemy import select,func
from .core import SessionLocal
from .models import AutomationTask,ComplianceResult,ManagedAsset,CheckResult,SystemAlert,Notification,DeviceConfigSnapshot,Document,Reminder,NetworkChangeJob

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
 except Exception as e:print("automation telegram:",e,flush=True)

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

def run_it(db):
 changed=[]
 for a in db.scalars(select(ManagedAsset).where(ManagedAsset.enabled==True)):
  old=a.last_status;status,lat,msg=probe(a);a.last_status=status;a.last_latency_ms=lat
  if status=="up":a.last_seen=datetime.utcnow()
  db.add(CheckResult(asset_id=a.id,status=status,latency_ms=lat,message=msg))
  if old=="up" and status=="down":
   db.add(SystemAlert(asset_id=a.id,severity="critical",title=f"{a.name} در دسترس نیست",body=msg));changed.append(f"DOWN: {a.name}")
  elif old=="down" and status=="up":
   db.add(Notification(kind="it_recovery",title=f"{a.name} دوباره در دسترس است",body="Service recovered"));changed.append(f"UP: {a.name}")
 return " | ".join(changed) or "health check completed"

def run_compliance(db,config):
 policies=(config or {}).get("policies",[])
 latest={}
 for s in db.scalars(select(DeviceConfigSnapshot).order_by(DeviceConfigSnapshot.created_at.desc())):
  if s.device_id not in latest:latest[s.device_id]=s
 total=fail=0
 for s in latest.values():
  txt=s.config_text.lower()
  for p in policies:
   total+=1;issues=[]
   for q in p.get("forbid",[]): 
    if str(q).lower() in txt:issues.append("forbidden: "+str(q))
   anyrules=[str(q).lower() for q in p.get("require_any",[])]
   if anyrules and not any(q in txt for q in anyrules):issues.append("require_any missing")
   for q in p.get("require",[]):
    if str(q).lower() not in txt:issues.append("required missing: "+str(q))
   status="fail" if issues else "pass"
   if issues:fail+=1
   db.add(ComplianceResult(device_id=s.device_id,device_name=s.device_name,policy_name=p.get("name","Policy"),status=status,detail="; ".join(issues) if issues else "OK"))
 return f"checked={total}, failed={fail}"

def daily_summary(db):
 docs=db.scalar(select(func.count()).select_from(Document).where(Document.deleted==False)) or 0
 reminders=db.scalar(select(func.count()).select_from(Reminder).where(Reminder.done==False)) or 0
 assets=db.scalar(select(func.count()).select_from(ManagedAsset)) or 0
 down=db.scalar(select(func.count()).select_from(ManagedAsset).where(ManagedAsset.last_status=="down")) or 0
 alerts=db.scalar(select(func.count()).select_from(SystemAlert).where(SystemAlert.acknowledged==False)) or 0
 failed=db.scalar(select(func.count()).select_from(NetworkChangeJob).where(NetworkChangeJob.status=="failed")) or 0
 comp=db.scalar(select(func.count()).select_from(ComplianceResult).where(ComplianceResult.status=="fail",ComplianceResult.checked_at>=datetime.utcnow()-timedelta(days=1))) or 0
 msg=f"📊 Hossein Hub Daily Summary\nDocuments: {docs}\nReminders: {reminders}\nIT Assets: {assets}\nDown: {down}\nOpen Alerts: {alerts}\nNetOps Failed: {failed}\nCompliance Failures (24h): {comp}"
 tg(msg)
 return msg

def ensure_defaults(db):
 if db.scalar(select(AutomationTask).limit(1)):return
 db.add_all([
  AutomationTask(name="IT Health Check",kind="it_check_all",interval_minutes=5,enabled=True,next_run=datetime.utcnow()),
  AutomationTask(name="NetOps Compliance",kind="compliance_scan",interval_minutes=60,enabled=True,config_json=json.dumps({"policies":[{"name":"No HTTP management","forbid":["ip http server","set admin-http enable"]}]},ensure_ascii=False),next_run=datetime.utcnow()),
  AutomationTask(name="Daily Management Summary",kind="daily_summary",interval_minutes=1440,enabled=True,next_run=datetime.utcnow())
 ]);db.commit()

while True:
 try:
  with SessionLocal() as db:
   ensure_defaults(db)
   now=datetime.utcnow()
   tasks=list(db.scalars(select(AutomationTask).where(AutomationTask.enabled==True,AutomationTask.next_run<=now)))
   for t in tasks:
    try:
     cfg=json.loads(t.config_json or "{}")
     if t.kind=="it_check_all":detail=run_it(db)
     elif t.kind=="compliance_scan":detail=run_compliance(db,cfg)
     elif t.kind=="daily_summary":detail=daily_summary(db)
     else:raise RuntimeError("Unknown task kind")
     t.last_status="success";t.last_error=None;t.last_run=now;t.next_run=now+timedelta(minutes=t.interval_minutes)
     db.add(Notification(kind="automation",title=f"Automation OK: {t.name}",body=detail[:1000]))
    except Exception as e:
     t.last_status="failed";t.last_error=str(e)[:1000];t.last_run=now;t.next_run=now+timedelta(minutes=t.interval_minutes)
     db.add(SystemAlert(severity="warning",title=f"Automation failed: {t.name}",body=str(e)[:500]))
    db.commit()
 except Exception as e:print("automation-worker:",e,flush=True)
 time.sleep(30)

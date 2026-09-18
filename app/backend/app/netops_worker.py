import os,json,time
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal
from .models import NetworkChangeJob,Audit,NetworkChangeValidation

ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"))
INV=ROOT/"devices.json"

def inventory():
 try:
  x=json.loads(INV.read_text())
  return x if isinstance(x,list) else []
 except:return []

def lines(s): return [x.strip() for x in (s or "").splitlines() if x.strip()]

def secret(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

def connect(d):
 from netmiko import ConnectHandler
 kw={
  "device_type":d.get("device_type","cisco_ios"),
  "host":d["host"],
  "port":int(d.get("port",22)),
  "username":secret(d.get("username_file","")) or d.get("username",""),
  "password":secret(d.get("password_file","")),
  "secret":secret(d.get("enable_secret_file","")),
  "fast_cli":False,
  "conn_timeout":12,
  "auth_timeout":15,
  "banner_timeout":15,
 }
 if d.get("key_file"): kw["use_keys"]=True;kw["key_file"]=str(ROOT/d["key_file"])
 return ConnectHandler(**kw)

def show_backup(c,d):
 t=d.get("device_type","")
 cmds=d.get("backup_commands")
 if not cmds:
  if "fortinet" in t:cmds=["show full-configuration"]
  elif "mikrotik" in t:cmds=["/export terse hide-sensitive"]
  elif "juniper" in t:cmds=["show configuration | display set"]
  elif "cisco" in t or "arista" in t:cmds=["show running-config"]
  else:cmds=["show configuration"]
 out=[]
 for cmd in cmds:
  try:out.append(f"$ {cmd}\n"+c.send_command(cmd,read_timeout=120))
  except Exception as e:out.append(f"$ {cmd}\nERROR: {e}")
 return "\n\n".join(out)

def run_show(c,cmds):
 out=[]
 for cmd in cmds:
  out.append(f"$ {cmd}\n"+c.send_command(cmd,read_timeout=90))
 return "\n\n".join(out)

def run_change(c,d,cmds):
 t=d.get("device_type","")
 if not cmds:return ""
 if "fortinet" in t:
  return c.send_config_set(cmds,exit_config_mode=False,read_timeout=180)
 if "mikrotik" in t:
  return "\n".join(c.send_command(x,read_timeout=90) for x in cmds)
 if "juniper" in t:
  out=c.send_config_set(cmds,read_timeout=180)
  try: out += "\n"+str(c.commit())
  except Exception as e: raise RuntimeError("Juniper commit failed: "+str(e))
  return out
 return c.send_config_set(cmds,read_timeout=180)

def validate_output(db,j):
 v=db.scalar(select(NetworkChangeValidation).where(NetworkChangeValidation.job_id==j.id))
 if not v:return
 try:must=json.loads(v.must_include_json or "[]")
 except:must=[]
 try:mustnot=json.loads(v.must_not_include_json or "[]")
 except:mustnot=[]
 text=(j.postcheck_output or "")+"\n"+(j.change_output or "")
 issues=[]
 for x in must:
  if str(x) not in text:issues.append("missing: "+str(x))
 for x in mustnot:
  if str(x) in text:issues.append("forbidden output present: "+str(x))
 v.checked_at=datetime.utcnow()
 if issues:
  v.status="failed";v.detail="; ".join(issues)
  raise RuntimeError("Post-change validation failed: "+v.detail)
 v.status="passed";v.detail="Validation passed"

def persist_change(c,d):
 t=d.get("device_type","")
 if d.get("save_after",True) is False:return ""
 if "cisco_ios" in t or "cisco_nxos" in t or "arista" in t:
  try:return str(c.save_config())
  except Exception as e:return "save warning: "+str(e)
 return ""

while True:
 try:
  with SessionLocal() as db:
   j=db.scalar(select(NetworkChangeJob).where(NetworkChangeJob.status=="queued").order_by(NetworkChangeJob.created_at))
   if not j:
    time.sleep(2);continue
   d=next((x for x in inventory() if str(x.get("id"))==j.device_id and x.get("enabled",True)),None)
   if not d:
    j.status="failed";j.error="Device not found or disabled";j.finished_at=datetime.utcnow();db.commit();continue
   j.status="running";j.started_at=datetime.utcnow();db.commit()
   conn=None
   try:
    conn=connect(d)
    if secret(d.get("enable_secret_file","")):
     try:conn.enable()
     except:pass
    j.backup_text=show_backup(conn,d)
    j.precheck_output=run_show(conn,lines(j.precheck_commands))
    j.change_output=run_change(conn,d,lines(j.change_commands))
    j.postcheck_output=run_show(conn,lines(j.postcheck_commands))
    validate_output(db,j)
    saved=persist_change(conn,d)
    if saved:j.change_output=(j.change_output or "")+"\n\n--- SAVE ---\n"+saved
    j.status="success";j.finished_at=datetime.utcnow()
    db.add(Audit(action="netops.change.success",object_type="network_device",object_id=j.id,detail=j.device_name))
   except Exception as e:
    j.status="failed";j.error=str(e)[:4000];j.finished_at=datetime.utcnow()
    if conn and lines(j.rollback_commands):
     try:
      rb=run_change(conn,d,lines(j.rollback_commands))
      j.change_output=(j.change_output or "")+"\n\n--- ROLLBACK ---\n"+rb
      db.add(Audit(action="netops.rollback.executed",object_type="network_device",object_id=j.id,detail=j.device_name))
     except Exception as re:
      j.error=(j.error or "")+"\nRollback failed: "+str(re)[:2000]
    db.add(Audit(action="netops.change.failed",object_type="network_device",object_id=j.id,detail=(j.error or "")[:1000]))
   finally:
    try:
     if conn:conn.disconnect()
    except:pass
   db.commit()
 except Exception as e:
  print("netops-worker:",e,flush=True);time.sleep(5)

import os,json,hashlib,difflib
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user,csrf_guard
from .core import get_db
from .models import DeviceConfigSnapshot,Audit

r=APIRouter(prefix="/api/netops-config",dependencies=[Depends(current_user)])
ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"))
INV=ROOT/"devices.json"

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

def inv():
 try:
  x=json.loads(INV.read_text());return x if isinstance(x,list) else []
 except:return []

def secret(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

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

@r.post("/{device_id}/backup",dependencies=[Depends(csrf_guard)])
def backup(device_id:str,db:Session=Depends(get_db),u=Depends(admin)):
 d=next((x for x in inv() if str(x.get("id"))==device_id and x.get("enabled",True)),None)
 if not d:raise HTTPException(404,"Device not found")
 c=None
 try:
  c=connect(d);cmd=backup_command(d.get("device_type") or "")
  text=c.send_command(cmd,read_timeout=180)
 except Exception as e:raise HTTPException(502,str(e)[:500])
 finally:
  try:
   if c:c.disconnect()
  except:pass
 sha=hashlib.sha256(text.encode()).hexdigest()
 last=db.scalar(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_id==device_id).order_by(DeviceConfigSnapshot.created_at.desc()))
 if last and last.sha256==sha:
  return {"ok":True,"changed":False,"snapshot_id":last.id,"sha256":sha,"bytes":len(text.encode())}
 s=DeviceConfigSnapshot(device_id=device_id,device_name=d.get("name") or device_id,config_text=text,sha256=sha,source="manual")
 db.add(s);db.flush();db.add(Audit(action="netops.backup.create",object_type="network_device",object_id=s.id,detail=s.device_name));db.commit()
 return {"ok":True,"changed":True,"snapshot_id":s.id,"sha256":sha,"bytes":len(text.encode())}

@r.get("/{device_id}/snapshots")
def snapshots(device_id:str,db:Session=Depends(get_db),u=Depends(admin)):
 rows=db.scalars(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_id==device_id).order_by(DeviceConfigSnapshot.created_at.desc()).limit(100))
 return [{"id":x.id,"created_at":x.created_at,"sha256":x.sha256,"bytes":len(x.config_text.encode()),"source":x.source} for x in rows]

@r.get("/snapshot/{snapshot_id}")
def snapshot(snapshot_id:str,db:Session=Depends(get_db),u=Depends(admin)):
 x=db.get(DeviceConfigSnapshot,snapshot_id)
 if not x:raise HTTPException(404)
 return {"id":x.id,"device_id":x.device_id,"device_name":x.device_name,"created_at":x.created_at,"sha256":x.sha256,"config_text":x.config_text}

@r.get("/{device_id}/diff")
def diff(device_id:str,db:Session=Depends(get_db),u=Depends(admin)):
 rows=list(db.scalars(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_id==device_id).order_by(DeviceConfigSnapshot.created_at.desc()).limit(2)))
 if len(rows)<2:return {"available":False,"diff":""}
 new,old=rows[0],rows[1]
 text="".join(difflib.unified_diff(old.config_text.splitlines(True),new.config_text.splitlines(True),fromfile=str(old.created_at),tofile=str(new.created_at)))
 return {"available":True,"old_id":old.id,"new_id":new.id,"diff":text[:200000]}

@r.post("/backup-all",dependencies=[Depends(csrf_guard)])
def backup_all(db:Session=Depends(get_db),u=Depends(admin)):
 results=[]
 for d in inv():
  if not d.get("enabled",True):continue
  if not d.get("username_file") or not d.get("password_file"):
   results.append({"device":d.get("name") or d.get("host"),"ok":False,"error":"No credentials"});continue
  c=None
  try:
   c=connect(d);cmd=backup_command(d.get("device_type") or "");text=c.send_command(cmd,read_timeout=180)
   sha=hashlib.sha256(text.encode()).hexdigest()
   last=db.scalar(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_id==str(d.get("id"))).order_by(DeviceConfigSnapshot.created_at.desc()))
   changed=not last or last.sha256!=sha
   if changed:
    s=DeviceConfigSnapshot(device_id=str(d.get("id")),device_name=d.get("name") or d.get("host") or str(d.get("id")),config_text=text,sha256=sha,source="manual-all")
    db.add(s);db.flush();db.add(Audit(action="netops.backup.manual_all",object_type="network_device",object_id=s.id,detail=s.device_name));db.commit()
   results.append({"device":d.get("name") or d.get("host"),"ok":True,"changed":changed,"bytes":len(text.encode())})
  except Exception as e:
   db.rollback();results.append({"device":d.get("name") or d.get("host"),"ok":False,"error":str(e)[:300]})
  finally:
   try:
    if c:c.disconnect()
   except:pass
 return {"total":len(results),"ok":sum(1 for x in results if x.get("ok")),"failed":sum(1 for x in results if not x.get("ok")),"changed":sum(1 for x in results if x.get("changed")),"results":results}

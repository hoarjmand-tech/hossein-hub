import json,os
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user,csrf_guard
from .core import get_db
from .models import NetworkChangeJob,Audit,NetworkChangePolicy
r=APIRouter(prefix="/api/netops",dependencies=[Depends(current_user)])
ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"))
INV=ROOT/"devices.json"

def inv():
 try:
  x=json.loads(INV.read_text())
  return x if isinstance(x,list) else []
 except:return []

def _secret(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

def _netmiko_test(d):
 from netmiko import ConnectHandler
 dtype=d.get("device_type") or "cisco_ios"
 kw={"device_type":dtype,"host":d["host"],"port":int(d.get("port",22)),"username":_secret(d.get("username_file","")) or d.get("username",""),"password":_secret(d.get("password_file","")),"secret":_secret(d.get("enable_secret_file","")),"fast_cli":False,"conn_timeout":8,"auth_timeout":10,"banner_timeout":10}
 c=ConnectHandler(**kw)
 try:
  if kw["secret"]:
   try:c.enable()
   except:pass
  cmd="get system status" if "fortinet" in dtype else ("/system resource print" if "mikrotik" in dtype else "show version")
  out=c.send_command(cmd,read_timeout=45)
  return {"ok":True,"command":cmd,"output":out[:12000],"prompt":c.find_prompt()}
 finally:
  try:c.disconnect()
  except:pass

def _change_policy_check(db,x):
 policies=list(db.scalars(select(NetworkChangePolicy).where(NetworkChangePolicy.enabled==True)))
 commands="\n".join(x.commands).lower()
 for p in policies:
  if p.require_precheck and not x.precheck:raise HTTPException(400,f"Policy {p.name}: pre-check required")
  if p.require_postcheck and not x.postcheck:raise HTTPException(400,f"Policy {p.name}: post-check required")
  if p.require_rollback and not x.rollback:raise HTTPException(400,f"Policy {p.name}: rollback required")
  try:blocked=json.loads(p.blocked_patterns_json or "[]")
  except:blocked=[]
  for pat in blocked:
   if str(pat).lower() in commands:raise HTTPException(400,f"Policy {p.name}: blocked command pattern: {pat}")

def _save_inv(devices):
 ROOT.mkdir(parents=True,exist_ok=True)
 INV.write_text(json.dumps(devices,ensure_ascii=False,indent=2))

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

class ImportDiscovered(BaseModel):
 devices:list[dict]

class DevicePatch(BaseModel):
 name:str|None=None
 host:str|None=None
 port:int|None=None
 device_type:str|None=None
 site:str|None=None
 role:str|None=None
 enabled:bool|None=None
 save_after:bool|None=None

class ReadCommand(BaseModel):
 command:str=Field(min_length=1,max_length=500)

class Change(BaseModel):
 device_id:str=Field(min_length=1,max_length=120)
 commands:list[str]=Field(min_length=1,max_length=500)
 precheck:list[str]=Field(default_factory=list,max_length=100)
 postcheck:list[str]=Field(default_factory=list,max_length=100)
 rollback:list[str]=Field(default_factory=list,max_length=500)

@r.get("/devices")
def devices(u=Depends(admin)):
 return [{k:d.get(k) for k in ("id","name","host","port","device_type","site","role","enabled")} for d in inv()]

@r.get("/jobs")
def jobs(limit:int=100,db:Session=Depends(get_db),u=Depends(admin)):
 rows=db.scalars(select(NetworkChangeJob).order_by(NetworkChangeJob.created_at.desc()).limit(min(limit,500)))
 return [{"id":x.id,"device_id":x.device_id,"device_name":x.device_name,"requested_by":x.requested_by,"status":x.status,"created_at":x.created_at,"started_at":x.started_at,"finished_at":x.finished_at,"error":x.error} for x in rows]

@r.get("/jobs/{jid}")
def job(jid:str,db:Session=Depends(get_db),u=Depends(admin)):
 x=db.get(NetworkChangeJob,jid)
 if not x:raise HTTPException(404)
 return {k:getattr(x,k) for k in ("id","device_id","device_name","requested_by","status","change_commands","precheck_commands","postcheck_commands","rollback_commands","backup_text","precheck_output","change_output","postcheck_output","error","created_at","started_at","finished_at")}

@r.post("/jobs",dependencies=[Depends(csrf_guard)])
def create(x:Change,db:Session=Depends(get_db),u=Depends(admin)):
 d=next((z for z in inv() if str(z.get("id"))==x.device_id and z.get("enabled",True)),None)
 if not d:raise HTTPException(404,"Device not found or disabled")
 _change_policy_check(db,x)
 j=NetworkChangeJob(device_id=x.device_id,device_name=d.get("name") or x.device_id,requested_by=u.username,status="queued",
  change_commands="\n".join(x.commands),precheck_commands="\n".join(x.precheck),postcheck_commands="\n".join(x.postcheck),rollback_commands="\n".join(x.rollback))
 db.add(j);db.flush();db.add(Audit(action="netops.change.queue",object_type="network_device",object_id=j.id,detail=f"{j.device_name} by {u.username}"));db.commit()
 return {"ok":True,"job_id":j.id,"status":"queued"}

@r.post("/devices/import-discovered",dependencies=[Depends(csrf_guard)])
def import_discovered(x:ImportDiscovered,u=Depends(admin)):
 devices=inv()
 byid={str(d.get("id")):d for d in devices}
 added=0;updated=0
 for z in x.devices:
  host=str(z.get("host") or "").strip()
  if not host: continue
  did="auto-"+host.replace(".","-").replace(":","-")
  d=byid.get(did,{})
  before=bool(d)
  d.update({
   "id":did,
   "name":z.get("name") or host,
   "host":host,
   "port":22 if 22 in (z.get("ports") or []) else (8291 if 8291 in (z.get("ports") or []) else 22),
   "device_type":z.get("device_type") or "unknown",
   "site":"auto-discovered",
   "role":z.get("role") or "unknown",
   "enabled":True,
   "discovered":True
  })
  byid[did]=d
  if before: updated+=1
  else: added+=1
 ROOT.mkdir(parents=True,exist_ok=True)
 INV.write_text(json.dumps(list(byid.values()),ensure_ascii=False,indent=2))
 return {"ok":True,"added":added,"updated":updated,"total":len(byid)}

@r.post("/devices/test-all",dependencies=[Depends(csrf_guard)])
def test_all(u=Depends(admin)):
 from datetime import datetime
 devices=inv();results=[];changed=False
 for d in devices:
  if not d.get("enabled",True):continue
  if not d.get("username_file") or not d.get("password_file"):
   results.append({"id":d.get("id"),"name":d.get("name"),"host":d.get("host"),"ok":False,"error":"No credentials"});continue
  try:
   x=_netmiko_test(d)
   d["connection_ok"]=True;d["last_test"]=datetime.utcnow().isoformat()+"Z";d["last_prompt"]=x.get("prompt");d["detected_summary"]=(x.get("output") or "")[:1200];changed=True
   results.append({"id":d.get("id"),"name":d.get("name"),"host":d.get("host"),"ok":True,"prompt":x.get("prompt"),"summary":(x.get("output") or "")[:500]})
  except Exception as e:
   d["connection_ok"]=False;d["last_test"]=datetime.utcnow().isoformat()+"Z";d["last_error"]=str(e)[:500];changed=True
   results.append({"id":d.get("id"),"name":d.get("name"),"host":d.get("host"),"ok":False,"error":str(e)[:500]})
 if changed:INV.write_text(json.dumps(devices,ensure_ascii=False,indent=2))
 return {"total":len(results),"ok":sum(1 for x in results if x["ok"]),"failed":sum(1 for x in results if not x["ok"]),"results":results}

@r.get("/devices/{device_id}")
def device_detail(device_id:str,db:Session=Depends(get_db),u=Depends(admin)):
 d=next((z for z in inv() if str(z.get("id"))==device_id),None)
 if not d:raise HTTPException(404,"Device not found")
 recent=list(db.scalars(select(NetworkChangeJob).where(NetworkChangeJob.device_id==device_id).order_by(NetworkChangeJob.created_at.desc()).limit(20)))
 return {"device":{k:d.get(k) for k in d.keys() if k not in ("password","username","password_file","username_file","enable_secret_file","key_file")},
 "jobs":[{"id":x.id,"status":x.status,"requested_by":x.requested_by,"created_at":x.created_at,"finished_at":x.finished_at,"error":x.error} for x in recent]}

@r.post("/devices/{device_id}/command",dependencies=[Depends(csrf_guard)])
def read_command(device_id:str,x:ReadCommand,u=Depends(admin)):
 d=next((z for z in inv() if str(z.get("id"))==device_id and z.get("enabled",True)),None)
 if not d:raise HTTPException(404,"Device not found")
 cmd=x.command.strip()
 low=cmd.lower()
 allowed=("show ","get ","diagnose ","display ","/system ","/interface print","/ip address print","/ip route print","/routing ","ping ","traceroute ")
 if not any(low.startswith(p) for p in allowed):
  raise HTTPException(400,"Only read-only operational commands are allowed here. Use Change Pipeline for configuration changes.")
 try:
  from netmiko import ConnectHandler
  dtype=d.get("device_type") or "cisco_ios"
  kw={"device_type":dtype,"host":d["host"],"port":int(d.get("port",22)),"username":_secret(d.get("username_file","")) or d.get("username",""),"password":_secret(d.get("password_file","")),"secret":_secret(d.get("enable_secret_file","")),"fast_cli":False,"conn_timeout":10,"auth_timeout":12,"banner_timeout":12}
  c=ConnectHandler(**kw)
  try:
   if kw["secret"]:
    try:c.enable()
    except:pass
   out=c.send_command(cmd,read_timeout=120)
   return {"ok":True,"device":d.get("name") or device_id,"command":cmd,"output":out[:200000]}
  finally:
   try:c.disconnect()
   except:pass
 except Exception as e:
  raise HTTPException(502,str(e)[:1000])

@r.patch("/devices/{device_id}",dependencies=[Depends(csrf_guard)])
def patch_device(device_id:str,x:DevicePatch,db:Session=Depends(get_db),u=Depends(admin)):
 devices=inv();d=next((z for z in devices if str(z.get("id"))==device_id),None)
 if not d:raise HTTPException(404,"Device not found")
 for k,v in x.model_dump(exclude_unset=True).items():
  if k=="host" and v is not None and not str(v).strip():raise HTTPException(400,"Host cannot be blank")
  d[k]=v
 _save_inv(devices)
 db.add(Audit(action="netops.device.update",object_type="network_device",object_id=device_id,detail=f"{d.get('name') or device_id} by {u.username}"));db.commit()
 return {"ok":True,"device":{k:d.get(k) for k in ("id","name","host","port","device_type","site","role","enabled","save_after")}}

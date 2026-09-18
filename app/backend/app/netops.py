import json,os
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user,csrf_guard
from .core import get_db
from .models import NetworkChangeJob,Audit
r=APIRouter(prefix="/api/netops",dependencies=[Depends(current_user)])
ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"))
INV=ROOT/"devices.json"

def inv():
 try:
  x=json.loads(INV.read_text())
  return x if isinstance(x,list) else []
 except:return []

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

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
 j=NetworkChangeJob(device_id=x.device_id,device_name=d.get("name") or x.device_id,requested_by=u.username,status="queued",
  change_commands="\n".join(x.commands),precheck_commands="\n".join(x.precheck),postcheck_commands="\n".join(x.postcheck),rollback_commands="\n".join(x.rollback))
 db.add(j);db.flush();db.add(Audit(action="netops.change.queue",object_type="network_device",object_id=j.id,detail=f"{j.device_name} by {u.username}"));db.commit()
 return {"ok":True,"job_id":j.id,"status":"queued"}

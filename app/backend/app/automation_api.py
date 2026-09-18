import json
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,csrf_guard
from .models import AutomationTask,ComplianceResult,Audit

r=APIRouter(prefix="/api/automation",dependencies=[Depends(current_user)])

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

class TaskState(BaseModel):
 enabled:bool

class TaskIn(BaseModel):
 name:str=Field(min_length=1,max_length=200)
 kind:str=Field(pattern="^(it_check_all|compliance_scan|daily_summary|topology_collect)$")
 interval_minutes:int=Field(ge=5,le=10080)
 enabled:bool=True
 config:dict={}

def ensure_defaults(db):
 if db.scalar(select(AutomationTask).limit(1)):return
 defaults=[
  AutomationTask(name="IT Health Check",kind="it_check_all",interval_minutes=5,enabled=True,next_run=datetime.utcnow()),
  AutomationTask(name="NetOps Compliance",kind="compliance_scan",interval_minutes=60,enabled=True,
   config_json=json.dumps({"policies":[{"name":"No HTTP server on network devices","forbid":["ip http server","set admin-http enable"]},{"name":"SSH/HTTPS management expected","require_any":["ssh","https","admin-https"]}]},ensure_ascii=False),next_run=datetime.utcnow()),
  AutomationTask(name="Daily Management Summary",kind="daily_summary",interval_minutes=1440,enabled=True,next_run=datetime.utcnow()),
  AutomationTask(name="Topology Discovery",kind="topology_collect",interval_minutes=360,enabled=True,next_run=datetime.utcnow())
 ]
 db.add_all(defaults);db.commit()

@r.get("/tasks")
def tasks(db:Session=Depends(get_db),u=Depends(admin)):
 ensure_defaults(db)
 rows=db.scalars(select(AutomationTask).order_by(AutomationTask.name))
 return [{"id":x.id,"name":x.name,"kind":x.kind,"interval_minutes":x.interval_minutes,"enabled":x.enabled,
 "config":json.loads(x.config_json or "{}"),"last_status":x.last_status,"last_error":x.last_error,
 "last_run":x.last_run,"next_run":x.next_run} for x in rows]

@r.post("/tasks",dependencies=[Depends(csrf_guard)])
def add(x:TaskIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=AutomationTask(name=x.name,kind=x.kind,interval_minutes=x.interval_minutes,enabled=x.enabled,
 config_json=json.dumps(x.config,ensure_ascii=False),next_run=datetime.utcnow())
 db.add(z);db.flush();db.add(Audit(action="automation.create",object_type="automation",object_id=z.id,detail=f"{x.kind} by {u.username}"));db.commit()
 return {"id":z.id}

@r.patch("/tasks/{tid}",dependencies=[Depends(csrf_guard)])
def edit(tid:str,x:TaskIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(AutomationTask,tid)
 if not z:raise HTTPException(404)
 z.name=x.name;z.kind=x.kind;z.interval_minutes=x.interval_minutes;z.enabled=x.enabled;z.config_json=json.dumps(x.config,ensure_ascii=False)
 if z.enabled and not z.next_run:z.next_run=datetime.utcnow()
 db.add(Audit(action="automation.update",object_type="automation",object_id=z.id,detail=f"{x.kind} by {u.username}"));db.commit()
 return {"ok":True}

@r.post("/tasks/{tid}/run-now",dependencies=[Depends(csrf_guard)])
def run_now(tid:str,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(AutomationTask,tid)
 if not z:raise HTTPException(404)
 z.next_run=datetime.utcnow();z.enabled=True;db.commit();return {"ok":True}

@r.get("/compliance")
def compliance(limit:int=200,db:Session=Depends(get_db),u=Depends(admin)):
 rows=db.scalars(select(ComplianceResult).order_by(ComplianceResult.checked_at.desc()).limit(min(limit,1000)))
 return [{"id":x.id,"device_id":x.device_id,"device_name":x.device_name,"policy_name":x.policy_name,
 "status":x.status,"detail":x.detail,"checked_at":x.checked_at} for x in rows]

@r.patch("/tasks/{tid}/state",dependencies=[Depends(csrf_guard)])
def task_state(tid:str,x:TaskState,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(AutomationTask,tid)
 if not z:raise HTTPException(404)
 z.enabled=x.enabled
 if x.enabled:z.next_run=datetime.utcnow()
 db.add(Audit(action="automation.state",object_type="automation",object_id=z.id,detail=f"enabled={x.enabled} by {u.username}"))
 db.commit();return {"ok":True}

@r.delete("/tasks/{tid}",dependencies=[Depends(csrf_guard)])
def delete_task(tid:str,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(AutomationTask,tid)
 if not z:raise HTTPException(404)
 db.add(Audit(action="automation.delete",object_type="automation",object_id=z.id,detail=f"{z.name} by {u.username}"))
 db.delete(z);db.commit();return {"ok":True}

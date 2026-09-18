import json,re
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,csrf_guard
from .models import NetworkConfigTemplate,NetworkChangePolicy,Audit

r=APIRouter(prefix="/api/netops-library",dependencies=[Depends(current_user)])

def admin(u=Depends(current_user)):
 if not u.is_admin: raise HTTPException(403,"Admin required")
 return u

class TemplateIn(BaseModel):
 name:str=Field(min_length=1,max_length=200)
 vendor:str="any"
 role:str="any"
 description:str|None=None
 precheck:str=""
 change_commands:str=Field(min_length=1)
 postcheck:str=""
 rollback:str=""
 variables:list[str]=[]
 enabled:bool=True

class RenderIn(BaseModel):
 values:dict[str,str]={}

class PolicyIn(BaseModel):
 name:str=Field(min_length=1,max_length=200)
 enabled:bool=True
 require_precheck:bool=False
 require_postcheck:bool=False
 require_rollback:bool=False
 blocked_patterns:list[str]=[]

def tj(x):
 return {"id":x.id,"name":x.name,"vendor":x.vendor,"role":x.role,"description":x.description,
 "precheck":x.precheck or "","change_commands":x.change_commands,"postcheck":x.postcheck or "",
 "rollback":x.rollback or "","variables":json.loads(x.variables_json or "[]"),"enabled":x.enabled,"created_at":x.created_at}

@r.get("/templates")
def templates(db:Session=Depends(get_db),u=Depends(admin)):
 return [tj(x) for x in db.scalars(select(NetworkConfigTemplate).order_by(NetworkConfigTemplate.name))]

@r.post("/templates",dependencies=[Depends(csrf_guard)])
def create_template(x:TemplateIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=NetworkConfigTemplate(name=x.name,vendor=x.vendor,role=x.role,description=x.description,precheck=x.precheck,
 change_commands=x.change_commands,postcheck=x.postcheck,rollback=x.rollback,variables_json=json.dumps(x.variables),enabled=x.enabled)
 db.add(z);db.flush();db.add(Audit(action="netops.template.create",object_type="netops_template",object_id=z.id,detail=f"{z.name} by {u.username}"));db.commit()
 return tj(z)

@r.patch("/templates/{tid}",dependencies=[Depends(csrf_guard)])
def update_template(tid:str,x:TemplateIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(NetworkConfigTemplate,tid)
 if not z:raise HTTPException(404)
 z.name=x.name;z.vendor=x.vendor;z.role=x.role;z.description=x.description;z.precheck=x.precheck;z.change_commands=x.change_commands;z.postcheck=x.postcheck;z.rollback=x.rollback;z.variables_json=json.dumps(x.variables);z.enabled=x.enabled
 db.add(Audit(action="netops.template.update",object_type="netops_template",object_id=z.id,detail=f"{z.name} by {u.username}"));db.commit()
 return tj(z)

@r.delete("/templates/{tid}",dependencies=[Depends(csrf_guard)])
def delete_template(tid:str,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(NetworkConfigTemplate,tid)
 if not z:raise HTTPException(404)
 db.add(Audit(action="netops.template.delete",object_type="netops_template",object_id=z.id,detail=f"{z.name} by {u.username}"));db.delete(z);db.commit();return {"ok":True}

@r.post("/templates/{tid}/render",dependencies=[Depends(csrf_guard)])
def render_template(tid:str,x:RenderIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(NetworkConfigTemplate,tid)
 if not z or not z.enabled:raise HTTPException(404)
 required=json.loads(z.variables_json or "[]")
 missing=[k for k in required if k not in x.values]
 if missing:raise HTTPException(400,{"missing":missing})
 def render(s):
  out=s or ""
  for k,v in x.values.items():out=out.replace("{{"+k+"}}",str(v))
  if re.search(r"{{[^{}]+}}",out):raise HTTPException(400,"Unresolved template variables")
  return out
 return {"template":tj(z),"precheck":render(z.precheck),"change_commands":render(z.change_commands),"postcheck":render(z.postcheck),"rollback":render(z.rollback)}

@r.get("/policies")
def policies(db:Session=Depends(get_db),u=Depends(admin)):
 rows=db.scalars(select(NetworkChangePolicy).order_by(NetworkChangePolicy.created_at.desc()))
 return [{"id":x.id,"name":x.name,"enabled":x.enabled,"require_precheck":x.require_precheck,"require_postcheck":x.require_postcheck,"require_rollback":x.require_rollback,"blocked_patterns":json.loads(x.blocked_patterns_json or "[]"),"created_at":x.created_at} for x in rows]

@r.post("/policies",dependencies=[Depends(csrf_guard)])
def create_policy(x:PolicyIn,db:Session=Depends(get_db),u=Depends(admin)):
 z=NetworkChangePolicy(name=x.name,enabled=x.enabled,require_precheck=x.require_precheck,require_postcheck=x.require_postcheck,require_rollback=x.require_rollback,blocked_patterns_json=json.dumps(x.blocked_patterns))
 db.add(z);db.flush();db.add(Audit(action="netops.policy.create",object_type="netops_policy",object_id=z.id,detail=f"{z.name} by {u.username}"));db.commit()
 return {"id":z.id}

@r.delete("/policies/{pid}",dependencies=[Depends(csrf_guard)])
def delete_policy(pid:str,db:Session=Depends(get_db),u=Depends(admin)):
 z=db.get(NetworkChangePolicy,pid)
 if not z:raise HTTPException(404)
 db.add(Audit(action="netops.policy.delete",object_type="netops_policy",object_id=z.id,detail=f"{z.name} by {u.username}"));db.delete(z);db.commit();return {"ok":True}

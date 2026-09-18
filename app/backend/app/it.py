import socket,time,urllib.request
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,csrf_guard
from .models import ManagedAsset,CheckResult,SystemAlert,Audit
r=APIRouter(prefix="/api/it",dependencies=[Depends(current_user),Depends(csrf_guard)])
class AssetIn(BaseModel):
 name:str=Field(min_length=1,max_length=200);kind:str="server";address:str=Field(min_length=1,max_length=300);port:int|None=None;protocol:str="tcp";notes:str|None=None;enabled:bool=True
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
@r.get("/assets")
def assets(db:Session=Depends(get_db)):return [{"id":x.id,"name":x.name,"kind":x.kind,"address":x.address,"port":x.port,"protocol":x.protocol,"enabled":x.enabled,"status":x.last_status,"latency_ms":x.last_latency_ms,"last_seen":x.last_seen,"notes":x.notes} for x in db.scalars(select(ManagedAsset).order_by(ManagedAsset.name))]
@r.post("/assets")
def add(x:AssetIn,db:Session=Depends(get_db)):
 a=ManagedAsset(**x.model_dump());db.add(a);db.flush();db.add(Audit(action="it.asset.create",object_type="asset",object_id=a.id));db.commit();return {"id":a.id}
@r.patch("/assets/{aid}")
def edit(aid:str,x:AssetIn,db:Session=Depends(get_db)):
 a=db.get(ManagedAsset,aid)
 if not a:raise HTTPException(404)
 for k,v in x.model_dump().items():setattr(a,k,v)
 db.commit();return {"ok":True}
@r.delete("/assets/{aid}")
def remove(aid:str,db:Session=Depends(get_db)):
 a=db.get(ManagedAsset,aid)
 if not a:raise HTTPException(404)
 db.delete(a);db.commit();return {"ok":True}
@r.post("/assets/{aid}/check")
def check(aid:str,db:Session=Depends(get_db)):
 a=db.get(ManagedAsset,aid)
 if not a:raise HTTPException(404)
 old=a.last_status;status,lat,msg=probe(a);a.last_status=status;a.last_latency_ms=lat
 if status=="up":a.last_seen=datetime.utcnow()
 db.add(CheckResult(asset_id=a.id,status=status,latency_ms=lat,message=msg))
 if old=="up" and status=="down":db.add(SystemAlert(asset_id=a.id,severity="critical",title=f"{a.name} در دسترس نیست",body=msg))
 db.commit();return {"status":status,"latency_ms":lat,"message":msg}
@r.post("/check-all")
def check_all(db:Session=Depends(get_db)):
 out=[]
 for a in db.scalars(select(ManagedAsset).where(ManagedAsset.enabled==True)):
  status,lat,msg=probe(a);old=a.last_status;a.last_status=status;a.last_latency_ms=lat
  if status=="up":a.last_seen=datetime.utcnow()
  db.add(CheckResult(asset_id=a.id,status=status,latency_ms=lat,message=msg))
  if old=="up" and status=="down":db.add(SystemAlert(asset_id=a.id,severity="critical",title=f"{a.name} در دسترس نیست",body=msg))
  out.append({"id":a.id,"name":a.name,"status":status,"latency_ms":lat})
 db.commit();return out
@r.get("/alerts")
def alerts(db:Session=Depends(get_db)):return [{"id":x.id,"asset_id":x.asset_id,"severity":x.severity,"title":x.title,"body":x.body,"acknowledged":x.acknowledged,"created_at":x.created_at} for x in db.scalars(select(SystemAlert).order_by(SystemAlert.created_at.desc()).limit(100))]
@r.post("/alerts/{xid}/ack")
def ack(xid:str,db:Session=Depends(get_db)):
 x=db.get(SystemAlert,xid)
 if not x:raise HTTPException(404)
 x.acknowledged=True;db.commit();return {"ok":True}
@r.get("/dashboard")
def dashboard(db:Session=Depends(get_db)):
 return {"assets":db.scalar(select(func.count()).select_from(ManagedAsset)) or 0,"up":db.scalar(select(func.count()).select_from(ManagedAsset).where(ManagedAsset.last_status=="up")) or 0,"down":db.scalar(select(func.count()).select_from(ManagedAsset).where(ManagedAsset.last_status=="down")) or 0,"alerts":db.scalar(select(func.count()).select_from(SystemAlert).where(SystemAlert.acknowledged==False)) or 0}

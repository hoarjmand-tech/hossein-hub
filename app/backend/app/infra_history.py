import json
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .auth import current_user
from .core import get_db
from .models import ConnectorSample
r=APIRouter(prefix="/api/infra-history",dependencies=[Depends(current_user)])

@r.get("/summary")
def summary(hours:int=Query(24,ge=1,le=720),db:Session=Depends(get_db)):
 since=datetime.utcnow()-timedelta(hours=hours);out={}
 for name in ("FortiGate","ESXi/vCenter","Veeam"):
  rows=list(db.scalars(select(ConnectorSample).where(ConnectorSample.connector==name,ConnectorSample.sampled_at>=since).order_by(ConnectorSample.sampled_at)))
  up=sum(1 for x in rows if x.status=="up");total=len(rows)
  out[name]={"samples":total,"uptime_pct":round(up*100/total,1) if total else None,"last_status":rows[-1].status if rows else "unknown","last_at":rows[-1].sampled_at if rows else None}
 return out

@r.get("/{connector}")
def history(connector:str,hours:int=Query(24,ge=1,le=720),limit:int=Query(288,ge=1,le=2000),db:Session=Depends(get_db)):
 since=datetime.utcnow()-timedelta(hours=hours)
 rows=list(db.scalars(select(ConnectorSample).where(ConnectorSample.connector==connector,ConnectorSample.sampled_at>=since).order_by(ConnectorSample.sampled_at.desc()).limit(limit)))
 rows.reverse()
 return [{"status":x.status,"at":x.sampled_at,"summary":json.loads(x.summary_json) if x.summary_json else {}} for x in rows]

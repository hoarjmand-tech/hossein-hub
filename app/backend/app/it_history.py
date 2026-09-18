from fastapi import APIRouter,Depends,Query,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import ManagedAsset,CheckResult
r=APIRouter(prefix="/api/it-history",dependencies=[Depends(current_user)])
@r.get("/{asset_id}")
def history(asset_id:str,limit:int=Query(100,le=1000),db:Session=Depends(get_db)):
 a=db.get(ManagedAsset,asset_id)
 if not a:raise HTTPException(404)
 rows=db.scalars(select(CheckResult).where(CheckResult.asset_id==asset_id).order_by(CheckResult.checked_at.desc()).limit(limit))
 return {"asset":{"id":a.id,"name":a.name},"checks":[{"status":x.status,"latency_ms":x.latency_ms,"message":x.message,"checked_at":x.checked_at} for x in rows]}

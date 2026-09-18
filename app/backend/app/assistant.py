from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,or_
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import Document,DocumentVersion,ManagedAsset,SystemAlert,NetworkChangeJob,DeviceConfigSnapshot
r=APIRouter(prefix="/api/assistant",dependencies=[Depends(current_user)])
@r.get("/search")
def search(q:str=Query(min_length=2,max_length=200),db:Session=Depends(get_db)):
 p=f"%{q}%";docs=db.scalars(select(Document).where(Document.deleted==False,or_(Document.title.ilike(p),Document.notes.ilike(p),Document.document_number.ilike(p),Document.issuer.ilike(p),Document.id.in_(select(DocumentVersion.document_id).where(DocumentVersion.ocr_text.ilike(p))))).limit(20))
 assets=db.scalars(select(ManagedAsset).where(or_(ManagedAsset.name.ilike(p),ManagedAsset.address.ilike(p),ManagedAsset.notes.ilike(p))).limit(20))
 alerts=db.scalars(select(SystemAlert).where(or_(SystemAlert.title.ilike(p),SystemAlert.body.ilike(p))).limit(20))
 jobs=db.scalars(select(NetworkChangeJob).where(or_(NetworkChangeJob.device_name.ilike(p),NetworkChangeJob.requested_by.ilike(p),NetworkChangeJob.error.ilike(p))).limit(20))
 snaps=db.scalars(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_name.ilike(p)).limit(20))
 return {"query":q,"documents":[{"id":x.id,"title":x.title,"category":x.category} for x in docs],"assets":[{"id":x.id,"name":x.name,"status":x.last_status,"address":x.address} for x in assets],"alerts":[{"id":x.id,"title":x.title,"severity":x.severity} for x in alerts],"netops_jobs":[{"id":x.id,"device":x.device_name,"status":x.status,"requested_by":x.requested_by} for x in jobs],"config_snapshots":[{"id":x.id,"device":x.device_name,"created_at":x.created_at} for x in snaps],"mode":"local-private-search"}

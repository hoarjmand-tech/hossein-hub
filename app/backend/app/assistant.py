from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,or_
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import Document,DocumentVersion,ManagedAsset,SystemAlert,NetworkChangeJob,DeviceConfigSnapshot,NetworkConfigTemplate,ComplianceResult,NetworkNeighborSnapshot
r=APIRouter(prefix="/api/assistant",dependencies=[Depends(current_user)])
@r.get("/search")
def search(q:str=Query(min_length=2,max_length=200),db:Session=Depends(get_db)):
 p=f"%{q}%";docs=db.scalars(select(Document).where(Document.deleted==False,or_(Document.title.ilike(p),Document.notes.ilike(p),Document.document_number.ilike(p),Document.issuer.ilike(p),Document.id.in_(select(DocumentVersion.document_id).where(DocumentVersion.ocr_text.ilike(p))))).limit(20))
 assets=db.scalars(select(ManagedAsset).where(or_(ManagedAsset.name.ilike(p),ManagedAsset.address.ilike(p),ManagedAsset.notes.ilike(p))).limit(20))
 alerts=db.scalars(select(SystemAlert).where(or_(SystemAlert.title.ilike(p),SystemAlert.body.ilike(p))).limit(20))
 jobs=db.scalars(select(NetworkChangeJob).where(or_(NetworkChangeJob.device_name.ilike(p),NetworkChangeJob.requested_by.ilike(p),NetworkChangeJob.error.ilike(p))).limit(20))
 snaps=db.scalars(select(DeviceConfigSnapshot).where(DeviceConfigSnapshot.device_name.ilike(p)).limit(20))
 templates=db.scalars(select(NetworkConfigTemplate).where(or_(NetworkConfigTemplate.name.ilike(p),NetworkConfigTemplate.description.ilike(p),NetworkConfigTemplate.vendor.ilike(p),NetworkConfigTemplate.role.ilike(p))).limit(20))
 compliance=db.scalars(select(ComplianceResult).where(or_(ComplianceResult.device_name.ilike(p),ComplianceResult.policy_name.ilike(p),ComplianceResult.detail.ilike(p))).limit(20))
 neighbors=db.scalars(select(NetworkNeighborSnapshot).where(or_(NetworkNeighborSnapshot.local_device_name.ilike(p),NetworkNeighborSnapshot.neighbor_name.ilike(p),NetworkNeighborSnapshot.neighbor_ip.ilike(p),NetworkNeighborSnapshot.platform.ilike(p))).limit(20))
 return {"query":q,"documents":[{"id":x.id,"title":x.title,"category":x.category} for x in docs],"assets":[{"id":x.id,"name":x.name,"status":x.last_status,"address":x.address} for x in assets],"alerts":[{"id":x.id,"title":x.title,"severity":x.severity} for x in alerts],"netops_jobs":[{"id":x.id,"device":x.device_name,"status":x.status,"requested_by":x.requested_by} for x in jobs],"config_snapshots":[{"id":x.id,"device":x.device_name,"created_at":x.created_at} for x in snaps],"templates":[{"id":x.id,"name":x.name,"vendor":x.vendor,"role":x.role} for x in templates],"compliance":[{"id":x.id,"device":x.device_name,"policy":x.policy_name,"status":x.status,"detail":x.detail} for x in compliance],"neighbors":[{"id":x.id,"local_device":x.local_device_name,"neighbor":x.neighbor_name,"ip":x.neighbor_ip,"platform":x.platform} for x in neighbors],"mode":"local-private-search"}

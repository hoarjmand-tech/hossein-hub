import csv,io
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import Document,ManagedAsset,SystemAlert,Audit,NetworkChangeJob,DeviceConfigSnapshot,ComplianceResult,AutomationTask,NetworkNeighborSnapshot,NetworkConfigTemplate,NetworkChangePolicy
r=APIRouter(prefix="/api/reports",dependencies=[Depends(current_user)])
@r.get("/documents.csv")
def docs(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["title","category","document_number","expiry_date","created_at"])
 for x in db.scalars(select(Document).where(Document.deleted==False).order_by(Document.created_at.desc())):w.writerow([x.title,x.category,x.document_number or "",x.expiry_date or "",x.created_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=documents.csv"})
@r.get("/assets.csv")
def assets(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["name","kind","address","port","status","latency_ms","last_seen"])
 for x in db.scalars(select(ManagedAsset).order_by(ManagedAsset.name)):w.writerow([x.name,x.kind,x.address,x.port or "",x.last_status,x.last_latency_ms or "",x.last_seen or ""])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=assets.csv"})

@r.get("/alerts.csv")
def alerts_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["severity","title","body","acknowledged","created_at"])
 for x in db.scalars(select(SystemAlert).order_by(SystemAlert.created_at.desc())):w.writerow([x.severity,x.title,x.body or "",x.acknowledged,x.created_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=alerts.csv"})

@r.get("/audit.csv")
def audit_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["action","object_type","object_id","detail","at"])
 for x in db.scalars(select(Audit).order_by(Audit.at.desc()).limit(5000)):w.writerow([x.action,x.object_type,x.object_id or "",x.detail or "",x.at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=audit.csv"})

@r.get("/netops-jobs.csv")
def netops_jobs_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["device","requested_by","status","created_at","started_at","finished_at","error"])
 for x in db.scalars(select(NetworkChangeJob).order_by(NetworkChangeJob.created_at.desc()).limit(5000)):w.writerow([x.device_name,x.requested_by,x.status,x.created_at,x.started_at or "",x.finished_at or "",x.error or ""])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=netops-jobs.csv"})

@r.get("/config-snapshots.csv")
def config_snapshots_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["device","source","sha256","created_at","bytes"])
 for x in db.scalars(select(DeviceConfigSnapshot).order_by(DeviceConfigSnapshot.created_at.desc()).limit(5000)):w.writerow([x.device_name,x.source,x.sha256,x.created_at,len(x.config_text.encode())])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=config-snapshots.csv"})

@r.get("/compliance.csv")
def compliance_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["device","policy","status","detail","checked_at"])
 for x in db.scalars(select(ComplianceResult).order_by(ComplianceResult.checked_at.desc()).limit(10000)):w.writerow([x.device_name,x.policy_name,x.status,x.detail or "",x.checked_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=compliance.csv"})

@r.get("/automation.csv")
def automation_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["name","kind","interval_minutes","enabled","last_status","last_run","next_run","last_error"])
 for x in db.scalars(select(AutomationTask).order_by(AutomationTask.name)):w.writerow([x.name,x.kind,x.interval_minutes,x.enabled,x.last_status,x.last_run or "",x.next_run or "",x.last_error or ""])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=automation.csv"})

@r.get("/topology.csv")
def topology_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["local_device","local_interface","neighbor_name","neighbor_ip","neighbor_interface","platform","protocol","collected_at"])
 for x in db.scalars(select(NetworkNeighborSnapshot).order_by(NetworkNeighborSnapshot.collected_at.desc()).limit(10000)):
  w.writerow([x.local_device_name,x.local_interface or "",x.neighbor_name or "",x.neighbor_ip or "",x.neighbor_interface or "",x.platform or "",x.protocol,x.collected_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=topology.csv"})

@r.get("/netops-templates.csv")
def templates_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["name","vendor","role","enabled","description","created_at"])
 for x in db.scalars(select(NetworkConfigTemplate).order_by(NetworkConfigTemplate.name)):w.writerow([x.name,x.vendor,x.role,x.enabled,x.description or "",x.created_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=netops-templates.csv"})

@r.get("/netops-policies.csv")
def policies_csv(db:Session=Depends(get_db)):
 b=io.StringIO();w=csv.writer(b);w.writerow(["name","enabled","require_precheck","require_postcheck","require_rollback","blocked_patterns","created_at"])
 for x in db.scalars(select(NetworkChangePolicy).order_by(NetworkChangePolicy.created_at.desc())):w.writerow([x.name,x.enabled,x.require_precheck,x.require_postcheck,x.require_rollback,x.blocked_patterns_json or "[]",x.created_at])
 return StreamingResponse(iter([b.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=netops-policies.csv"})

import csv,io
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import Document,ManagedAsset,SystemAlert
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

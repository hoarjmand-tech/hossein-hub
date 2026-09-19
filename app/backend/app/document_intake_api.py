import os,uuid,shutil,json
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT,MAX_UPLOAD
from .auth import current_user,csrf_guard
from .models import DocumentIntakeItem,DocumentSourceState,Document

r=APIRouter(prefix="/api/intake",dependencies=[Depends(current_user)])
INBOX=ARCHIVE_ROOT/"intake";DRIVE=ARCHIVE_ROOT/"drive-inbox"
INBOX.mkdir(parents=True,exist_ok=True);DRIVE.mkdir(parents=True,exist_ok=True)

@r.post("/upload",dependencies=[Depends(csrf_guard)])
def upload(files:list[UploadFile]=File(...)):
 out=[]
 for f in files[:50]:
  name=Path(f.filename or "document").name
  target=INBOX/f"{uuid.uuid4()}__{name}"
  n=0
  with target.open("wb") as z:
   while b:=f.file.read(1048576):
    n+=len(b)
    if n>MAX_UPLOAD:
     target.unlink(missing_ok=True);raise HTTPException(413,f"{name}: file too large")
    z.write(b)
  out.append({"name":name,"bytes":n,"queued":True})
 return {"queued":out,"count":len(out)}

@r.get("/status")
def status(db:Session=Depends(get_db)):
 states={x.source:x for x in db.scalars(select(DocumentSourceState))}
 def s(name):
  x=states.get(name)
  return {"source":name,"last_scan_at":x.last_scan_at if x else None,"last_success_at":x.last_success_at if x else None,
   "last_error":x.last_error if x else None,"items_seen":x.items_seen if x else 0,"items_imported":x.items_imported if x else 0,
   "duplicates_ignored":x.duplicates_ignored if x else 0}
 return {"local":s("local"),"google_drive":s("google_drive"),
  "queued_local":sum(1 for x in INBOX.iterdir() if x.is_file()),"queued_drive":sum(1 for x in DRIVE.iterdir() if x.is_file())}

@r.get("/history")
def history(include_duplicates:bool=Query(False),limit:int=Query(100,le=500),db:Session=Depends(get_db)):
 q=select(DocumentIntakeItem)
 if not include_duplicates:q=q.where(DocumentIntakeItem.status!="duplicate")
 rows=db.scalars(q.order_by(DocumentIntakeItem.first_seen.desc()).limit(limit))
 return [{"id":x.id,"source":x.source,"original_name":x.original_name,"status":x.status,"document_id":x.document_id,
  "title":x.detected_title,"category":x.detected_category,"subtype":x.detected_subtype,"country":x.detected_country,
  "issuer":x.detected_issuer,"number":x.detected_number,"issue_date":x.detected_issue_date,"expiry_date":x.detected_expiry_date,
  "meta":json.loads(x.extracted_json or "{}"),"first_seen":x.first_seen,"processed_at":x.processed_at,"error":x.error} for x in rows]

@r.get("/recent-documents")
def recent_documents(limit:int=30,db:Session=Depends(get_db)):
 rows=db.scalars(select(DocumentIntakeItem).where(DocumentIntakeItem.status=="imported").order_by(DocumentIntakeItem.processed_at.desc()).limit(min(limit,100)))
 return [{"document_id":x.document_id,"title":x.detected_title,"category":x.detected_category,"source":x.source,"processed_at":x.processed_at} for x in rows]

import os,uuid,shutil,json
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Query,Form
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT,MAX_UPLOAD
from .auth import current_user,csrf_guard
from .models import DocumentIntakeItem,DocumentSourceState,Document

r=APIRouter(prefix="/api/intake",dependencies=[Depends(current_user)])

from pydantic import BaseModel
from datetime import date
from .models import DocumentVersion,Audit
from .document_intelligence import classify,canonical_filename

class MetadataPatch(BaseModel):
 title:str|None=None
 category:str|None=None
 subtype:str|None=None
 country:str|None=None
 issuer:str|None=None
 document_number:str|None=None
 issue_date:date|None=None
 expiry_date:date|None=None
 notes:str|None=None
 person_id:str|None=None
 case_id:str|None=None
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

@r.patch("/documents/{did}/metadata",dependencies=[Depends(csrf_guard)])
def update_metadata(did:str,x:MetadataPatch,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404,"Document not found")
 for k,v in x.model_dump(exclude_unset=True).items():setattr(d,k,v)
 db.add(Audit(action="document.intake.metadata_update",object_type="document",object_id=did,detail="manual review"))
 db.commit()
 return {"ok":True,"document_id":did}

@r.post("/documents/{did}/reclassify",dependencies=[Depends(csrf_guard)])
def reclassify(did:str,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404,"Document not found")
 v=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==did).order_by(DocumentVersion.version.desc()))
 if not v:raise HTTPException(404,"Version not found")
 from .services import extract_text
 p=ARCHIVE_ROOT/"documents"/v.stored_name
 text=extract_text(p,v.mime_type) if p.exists() else (v.ocr_text or "")
 if text:v.ocr_text=text;v.ocr_status="done"
 meta=classify(text or "",v.original_name or "")
 d.title=meta["title"];d.category=meta["category"];d.subtype=meta["subtype"];d.country=meta["country"];d.issuer=meta["issuer"];d.document_number=meta["document_number"];d.issue_date=meta["issue_date"];d.expiry_date=meta["expiry_date"];v.original_name=canonical_filename(meta,Path(v.original_name or "").suffix)
 item=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.document_id==did).order_by(DocumentIntakeItem.first_seen.desc()))
 if item:
  item.detected_title=meta["title"];item.detected_category=meta["category"];item.detected_subtype=meta["subtype"];item.detected_country=meta["country"];item.detected_issuer=meta["issuer"];item.detected_number=meta["document_number"];item.detected_issue_date=meta["issue_date"];item.detected_expiry_date=meta["expiry_date"]
  item.extracted_json=json.dumps({"confidence":meta["confidence"],"canonical_filename":canonical_filename(meta,Path(v.original_name or "").suffix)},ensure_ascii=False)
 db.add(Audit(action="document.intake.reclassify",object_type="document",object_id=did,detail=meta["confidence"]))
 db.commit()
 return {"ok":True,"meta":meta}

@r.get("/review")
def review(limit:int=100,db:Session=Depends(get_db)):
 rows=db.scalars(select(DocumentIntakeItem).where(DocumentIntakeItem.status=="imported").order_by(DocumentIntakeItem.processed_at.desc()).limit(min(limit,500)))
 out=[]
 for x in rows:
  meta=json.loads(x.extracted_json or "{}")
  if meta.get("confidence") not in ("low","medium"):continue
  d=db.get(Document,x.document_id) if x.document_id else None
  out.append({"intake_id":x.id,"document_id":x.document_id,"original_name":x.original_name,"confidence":meta.get("confidence"),"canonical_filename":meta.get("canonical_filename"),"document":None if not d else {"title":d.title,"category":d.category,"subtype":d.subtype,"country":d.country,"issuer":d.issuer,"document_number":d.document_number,"issue_date":d.issue_date,"expiry_date":d.expiry_date,"person_id":d.person_id,"case_id":d.case_id}})
 return out


@r.post("/bulk-reclassify",dependencies=[Depends(csrf_guard)])
def bulk_reclassify(db:Session=Depends(get_db)):
 from .services import extract_text
 rows=list(db.scalars(select(Document).where(Document.deleted==False)))
 done=0
 for d in rows:
  v=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==d.id).order_by(DocumentVersion.version.desc()))
  if not v: continue
  p=ARCHIVE_ROOT/"documents"/v.stored_name
  text=extract_text(p,v.mime_type) if p.exists() else (v.ocr_text or "")
  if text: v.ocr_text=text;v.ocr_status="done"
  meta=classify(text or "",v.original_name or "")
  ext=Path(v.original_name or "").suffix
  canonical=canonical_filename(meta,ext)
  d.title=meta["title"];d.category=meta["category"];d.subtype=meta["subtype"];d.country=meta["country"];d.issuer=meta["issuer"];d.document_number=meta["document_number"];d.issue_date=meta["issue_date"];d.expiry_date=meta["expiry_date"]
  v.original_name=canonical
  item=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.document_id==d.id).order_by(DocumentIntakeItem.first_seen.desc()))
  if item:
   item.detected_title=meta["title"];item.detected_category=meta["category"];item.detected_subtype=meta["subtype"];item.detected_country=meta["country"];item.detected_issuer=meta["issuer"];item.detected_number=meta["document_number"];item.detected_issue_date=meta["issue_date"];item.detected_expiry_date=meta["expiry_date"]
   old=json.loads(item.extracted_json or "{}");old.update({"confidence":meta["confidence"],"canonical_filename":canonical,"person_name":meta.get("person_name"),"reprocessed":True});item.extracted_json=json.dumps(old,ensure_ascii=False)
  done+=1
 db.add(Audit(action="document.intake.bulk_reclassify",object_type="document",object_id=None,detail=str(done)));db.commit()
 return {"ok":True,"processed":done}

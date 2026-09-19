import json, os
from pathlib import Path
from sqlalchemy import select
from .core import SessionLocal, ARCHIVE_ROOT
from .models import Document, DocumentVersion, DocumentIntakeItem, Audit
from .services import extract_text
from .document_intelligence import classify, canonical_filename

DOCS=ARCHIVE_ROOT/"documents"

def process(db,d,v):
 p=DOCS/v.stored_name
 if not p.exists(): return False
 text=extract_text(p,v.mime_type) or v.ocr_text or ""
 item=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.document_id==d.id).order_by(DocumentIntakeItem.first_seen.desc()))
 source_name=item.original_name if item and item.original_name else (v.original_name or "")
 meta=classify(text,source_name)
 ext=p.suffix.lower()[:15]
 canonical=canonical_filename(meta,ext)
 v.ocr_text=text or None
 v.ocr_status="done" if text else "pending"
 # Never degrade a useful filename to generic Document.*
 if meta.get("subtype")=="other" and canonical.lower().startswith("document."):
  canonical=v.original_name or canonical
 v.original_name=canonical
 d.title=meta["title"];d.category=meta["category"];d.subtype=meta["subtype"]
 d.country=meta["country"];d.issuer=meta["issuer"];d.document_number=meta["document_number"]
 d.issue_date=meta["issue_date"];d.expiry_date=meta["expiry_date"]
 if item:
  item.detected_title=meta["title"];item.detected_category=meta["category"];item.detected_subtype=meta["subtype"]
  item.detected_country=meta["country"];item.detected_issuer=meta["issuer"];item.detected_number=meta["document_number"]
  item.detected_issue_date=meta["issue_date"];item.detected_expiry_date=meta["expiry_date"]
  try: old=json.loads(item.extracted_json or "{}")
  except Exception: old={}
  old.update({"confidence":meta["confidence"],"canonical_filename":canonical,"person_name":meta.get("person_name"),"reprocessed":True})
  item.extracted_json=json.dumps(old,ensure_ascii=False)
 db.add(Audit(action="document.intake.reprocess",object_type="document",object_id=d.id,detail=canonical))
 return True

with SessionLocal() as db:
 n=0
 items=list(db.scalars(select(DocumentIntakeItem).where(DocumentIntakeItem.status=="imported",DocumentIntakeItem.document_id!=None).order_by(DocumentIntakeItem.first_seen)))
 seen=set()
 for item in items:
  if item.document_id in seen: continue
  seen.add(item.document_id)
  d=db.get(Document,item.document_id)
  if not d or d.deleted: continue
  v=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==d.id).order_by(DocumentVersion.version.desc()))
  if v and process(db,d,v):
   db.commit();n+=1;print(f"REPROCESSED {n}: {v.original_name}",flush=True)
 print(f"REPROCESS COMPLETE: {n}",flush=True)

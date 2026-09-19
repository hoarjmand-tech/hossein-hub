import time,json,re
from pathlib import Path
from sqlalchemy import select,or_
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem,Audit
from .services import extract_text,thumbnail
from .document_intelligence import classify,canonical_filename

DOCS=ARCHIVE_ROOT/"documents"
PREV=ARCHIVE_ROOT/"previews"
INTELLIGENCE_VERSION=3

def _item(db,did):
 return db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.document_id==did).order_by(DocumentIntakeItem.first_seen.desc()))

def _meta(item):
 try:return json.loads(item.extracted_json or "{}") if item else {}
 except Exception:return {}

def _needs_enrichment(db,v):
 d=db.get(Document,v.document_id)
 if not d:return False
 item=_item(db,d.id)
 meta=_meta(item)
 if int(meta.get("intelligence_version",0) or 0)<INTELLIGENCE_VERSION:return True
 if d.category=="other":return True
 if re.match(r"^(scan|img|image|document|doc)[ _-]*\d",d.title or "",re.I):return True
 return False

def enrich(db,v,force_ocr=False):
 p=DOCS/v.stored_name
 text=v.ocr_text or ""
 if force_ocr or len(text.strip())<40:
  text=extract_text(p,v.mime_type)
  v.ocr_text=text
 v.ocr_status="done" if text else "empty"
 thumbnail(p,v.mime_type,PREV/f"{v.id}.jpg")

 d=db.get(Document,v.document_id)
 if not d:return

 item=_item(db,d.id)
 data=_meta(item)
 meta=classify(text,v.original_name or "")

 # Any usable OCR heading is better than a scanner-generated filename.
 allow_title=meta["confidence"] in ("medium","high") and meta["title"]
 if allow_title:
  d.title=meta["title"]
  d.category=meta["category"]
  d.subtype=meta["subtype"]
  d.country=meta["country"]
  d.issuer=meta["issuer"]
  d.document_number=meta["document_number"]
  d.issue_date=meta["issue_date"]
  d.expiry_date=meta["expiry_date"]
  ext=Path(v.original_name or "document").suffix
  v.original_name=canonical_filename(meta,ext)

 if item:
  item.detected_title=d.title
  item.detected_category=d.category
  item.detected_subtype=d.subtype
  item.detected_country=d.country
  item.detected_issuer=d.issuer
  item.detected_number=d.document_number
  item.detected_issue_date=d.issue_date
  item.detected_expiry_date=d.expiry_date
  data.update({
   "intelligence_version":INTELLIGENCE_VERSION,
   "confidence":meta["confidence"],
   "score":meta.get("score"),
   "matched":meta.get("matched",[]),
   "subject":meta.get("subject"),
   "heading":meta.get("heading"),
   "canonical_filename":v.original_name,
   "ocr_enriched":bool(text),
  })
  item.extracted_json=json.dumps(data,ensure_ascii=False)

 db.add(Audit(action="document.ocr.enrich",object_type="document",object_id=d.id,detail=f'v{INTELLIGENCE_VERSION}:{meta["confidence"]}:{d.title}'))

def next_version(db):
 v=db.scalar(select(DocumentVersion).where(DocumentVersion.ocr_status=="pending").order_by(DocumentVersion.created_at).limit(1))
 if v:return v,False

 # Self-heal documents imported before the current intelligence engine.
 candidates=list(db.scalars(
  select(DocumentVersion)
  .join(Document,Document.id==DocumentVersion.document_id)
  .where(Document.deleted==False,DocumentVersion.ocr_status.in_(["done","empty","failed"]))
  .order_by(DocumentVersion.created_at.desc())
  .limit(100)
 ))
 for x in candidates:
  if _needs_enrichment(db,x):
   return x,True
 return None,False

while True:
 try:
  with SessionLocal() as db:
   v,force=next_version(db)
   if not v:
    time.sleep(3)
    continue
   v.ocr_status="processing"
   db.commit()
   try:
    enrich(db,v,force_ocr=force)
   except Exception as e:
    v.ocr_status="failed"
    item=_item(db,v.document_id)
    if item:
     data=_meta(item);data["intelligence_version"]=INTELLIGENCE_VERSION;data["intelligence_error"]=str(e)[:500]
     item.extracted_json=json.dumps(data,ensure_ascii=False)
    print("ocr-worker:",v.id,e,flush=True)
   db.commit()
 except Exception as e:
  print("ocr-worker-loop:",e,flush=True)
  time.sleep(5)

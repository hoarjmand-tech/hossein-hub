import json,re
from pathlib import Path
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem
from .services import extract_text
from .document_preprocess import enhanced_tesseract
from .document_intelligence import classify,canonical_filename

DOCS=ARCHIVE_ROOT/"documents"\nLIMIT=int(__import__("os").getenv("OCR_PREVIEW_LIMIT","0"))
def quality(text):
 n=len((text or "").strip())
 if n>=800:return "high"
 if n>=200:return "medium"
 return "low"

with SessionLocal() as db:
 items=list(db.scalars(select(DocumentIntakeItem).where(DocumentIntakeItem.status=="imported",DocumentIntakeItem.document_id!=None).order_by(DocumentIntakeItem.first_seen)))
 seen=set();n=0
 for item in items:
  if item.document_id in seen:continue
  seen.add(item.document_id)
  d=db.get(Document,item.document_id)
  if not d or d.deleted:continue
  v=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==d.id).order_by(DocumentVersion.version.desc()))
  if not v:continue
  p=DOCS/v.stored_name
  if not p.exists():continue
  text=extract_text(p,v.mime_type) or v.ocr_text or ""
  if p.suffix.lower() in (".jpg",".jpeg",".png",".webp",".tif",".tiff"):
   improved=enhanced_tesseract(p)
   if len(improved.strip())>len(text.strip()): text=improved
  meta=classify(text,item.original_name or v.original_name or "")
  conf=meta.get("confidence") or quality(text)
  proposed=canonical_filename(meta,p.suffix.lower() or Path(v.original_name or "").suffix.lower())
  safe=conf=="high" and not proposed.lower().startswith("document.")
  n+=1
  print(json.dumps({"n":n,"current":v.original_name,"source":item.original_name,"ocr_chars":len(text),"type":meta.get("subtype"),"title":meta.get("title"),"proposed":proposed,"confidence":conf,"rename_safe":safe},ensure_ascii=False),flush=True)
 print("OCR PREVIEW COMPLETE:",n,flush=True)

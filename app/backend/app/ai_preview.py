import json
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem
from .services import extract_text
from .local_document_ai import analyze_document

DOCS=ARCHIVE_ROOT/"documents"
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
  ai=analyze_document(text,item.original_name or v.original_name or "")
  n+=1
  print(json.dumps({"n":n,"id":d.id,"current":v.original_name,"source":item.original_name,"ocr_chars":len(text),"ai":ai},ensure_ascii=False),flush=True)
 print("AI PREVIEW COMPLETE:",n,flush=True)

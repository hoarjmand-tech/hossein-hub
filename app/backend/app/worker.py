import time
from pathlib import Path
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import DocumentVersion
from .services import extract_text,thumbnail
DOCS=ARCHIVE_ROOT/"documents";PREV=ARCHIVE_ROOT/"previews"
while True:
 try:
  with SessionLocal() as db:
   v=db.scalar(select(DocumentVersion).where(DocumentVersion.ocr_status=="pending").order_by(DocumentVersion.created_at).limit(1))
   if not v:time.sleep(3);continue
   v.ocr_status="processing";db.commit()
   p=DOCS/v.stored_name
   try:
    v.ocr_text=extract_text(p,v.mime_type);v.ocr_status="done" if v.ocr_text else "empty";thumbnail(p,v.mime_type,PREV/f"{v.id}.jpg")
   except Exception:v.ocr_status="failed"
   db.commit()
 except Exception:time.sleep(5)

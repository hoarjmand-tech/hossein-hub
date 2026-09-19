import time,json
from pathlib import Path
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem,Audit
from .services import extract_text,thumbnail
from .document_intelligence import classify,canonical_filename

DOCS=ARCHIVE_ROOT/"documents";PREV=ARCHIVE_ROOT/"previews"

def enrich(db,v):
    p=DOCS/v.stored_name
    text=extract_text(p,v.mime_type)
    v.ocr_text=text
    v.ocr_status="done" if text else "empty"
    thumbnail(p,v.mime_type,PREV/f"{v.id}.jpg")

    d=db.get(Document,v.document_id)
    if not d or not text:
        return

    meta=classify(text,v.original_name or "")
    if meta.get("confidence")=="low":
        return

    d.title=meta["title"]
    d.category=meta["category"]
    d.subtype=meta["subtype"]
    d.country=meta["country"]
    d.issuer=meta["issuer"]
    d.document_number=meta["document_number"]
    d.issue_date=meta["issue_date"]
    d.expiry_date=meta["expiry_date"]

    old_name=v.original_name or "document"
    ext=Path(old_name).suffix
    new_name=canonical_filename(meta,ext)
    v.original_name=new_name

    item=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.document_id==d.id).order_by(DocumentIntakeItem.first_seen.desc()))
    if item:
        item.detected_title=d.title
        item.detected_category=d.category
        item.detected_subtype=d.subtype
        item.detected_country=d.country
        item.detected_issuer=d.issuer
        item.detected_number=d.document_number
        item.detected_issue_date=d.issue_date
        item.detected_expiry_date=d.expiry_date
        data=json.loads(item.extracted_json or "{}")
        data.update({"confidence":meta["confidence"],"canonical_filename":new_name,"ocr_enriched":True})
        item.extracted_json=json.dumps(data,ensure_ascii=False)

    db.add(Audit(action="document.ocr.enrich",object_type="document",object_id=d.id,detail=f'{meta["confidence"]}:{new_name}'))

while True:
    try:
        with SessionLocal() as db:
            v=db.scalar(select(DocumentVersion).where(DocumentVersion.ocr_status=="pending").order_by(DocumentVersion.created_at).limit(1))
            if not v:
                time.sleep(3)
                continue
            v.ocr_status="processing"
            db.commit()
            try:
                enrich(db,v)
            except Exception as e:
                v.ocr_status="failed"
                print("ocr-worker:",v.id,e,flush=True)
            db.commit()
    except Exception as e:
        print("ocr-worker-loop:",e,flush=True)
        time.sleep(5)

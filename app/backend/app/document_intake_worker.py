import hashlib,json,os,shutil,time,uuid
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem,DocumentSourceState,Audit,Tag,DocumentTag,Person
from .services import detected_mime,extract_text,thumbnail
from .document_intelligence import classify,canonical_filename
from .local_document_ai import analyze_document

DOCS=ARCHIVE_ROOT/"documents"
PREV=ARCHIVE_ROOT/"previews"
SOURCES=[
 ("local",ARCHIVE_ROOT/"intake"),
 ("google_drive",ARCHIVE_ROOT/"drive-inbox"),
]
ALLOWED={"application/pdf","image/jpeg","image/png","image/webp","image/tiff"}

for source,p in SOURCES:
 p.mkdir(parents=True,exist_ok=True)

def sha256(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()

def match_person(db,text):
 t=" ".join((text or "").lower().split())
 hits=[]
 for p in db.scalars(select(Person)):
  n=" ".join((p.name or "").lower().split())
  if len(n)>=4 and n in t:hits.append(p)
 return hits[0].id if len(hits)==1 else None

def source_state(db,name):
 x=db.scalar(select(DocumentSourceState).where(DocumentSourceState.source==name))
 if not x:
  x=DocumentSourceState(source=name);db.add(x);db.flush()
 return x

def handle(db,source,p):
 st=source_state(db,source);st.items_seen+=1
 already=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.source==source,DocumentIntakeItem.source_key==str(p),DocumentIntakeItem.status.in_(["imported","duplicate"])))
 if already:return
 mime=detected_mime(p)
 if mime not in ALLOWED:
  q=DocumentIntakeItem(source=source,source_key=str(p),original_name=p.name,sha256="",status="rejected",error="unsupported file type",processed_at=datetime.utcnow())
  db.add(q);db.commit();p.unlink(missing_ok=True);return

 sh=sha256(p)
 prior=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sh))
 if prior:
  st.duplicates_ignored+=1
  db.add(DocumentIntakeItem(source=source,source_key=str(p),original_name=p.name,sha256=sh,status="duplicate",document_id=prior.document_id,processed_at=datetime.utcnow()))
  db.add(Audit(action="document.intake.duplicate_ignored",object_type="document",object_id=prior.document_id,detail=f"{source}:{p.name}"))
  db.commit()
  if source!="google_drive":p.unlink(missing_ok=True)
  return

 existing=db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.sha256==sh,DocumentIntakeItem.status=="imported"))
 if existing:
  st.duplicates_ignored+=1;db.commit()
  if source!="google_drive":p.unlink(missing_ok=True)
  return

 text=""
 try:text=extract_text(p,mime) or ""
 except Exception:pass
 meta=classify(text,p.name)
 ai=analyze_document(text,p.name)
 if ai and ai.get("confidence") in ("high","medium"):
  if ai.get("title"): meta["title"]=str(ai["title"])[:180]
  if ai.get("document_type") and meta.get("subtype")=="other": meta["subtype"]=str(ai["document_type"])[:80]
  for k in ("person_name","country","issuer","document_number"):
   if ai.get(k): meta[k]=str(ai[k])[:160]
  meta["confidence"]=ai["confidence"]
 ext=p.suffix.lower()[:15]
 canonical=canonical_filename(meta,ext)

 person_id=match_person(db,text)
 d=Document(
  title=meta["title"],category=meta["category"],subtype=meta["subtype"],country=meta["country"],issuer=meta["issuer"],
  document_number=meta["document_number"],issue_date=meta["issue_date"],expiry_date=meta["expiry_date"],
  person_id=person_id,notes=f"Auto-imported from {source}. Original filename: {p.name}"
 )
 db.add(d);db.flush()
 stored=f"{d.id}/v1-{uuid.uuid4()}{ext}"
 dest=DOCS/stored;dest.parent.mkdir(parents=True,exist_ok=True)
 if source=="google_drive":
  try:os.link(p,dest)
  except Exception:shutil.copy2(str(p),str(dest))
 else:
  shutil.move(str(p),str(dest))
 v=DocumentVersion(document_id=d.id,version=1,kind="original",original_name=canonical,stored_name=stored,mime_type=mime,size=dest.stat().st_size,sha256=sh,ocr_status="done" if text else "pending",ocr_text=text or None)
 db.add(v);db.flush()
 auto_tags=[source,meta.get("category"),meta.get("subtype"),meta.get("country"),meta.get("issuer"),"confidence-"+meta.get("confidence","low")]
 for raw in [x for x in auto_tags if x]:
  name=str(raw).strip().lower()[:100]
  t=db.scalar(select(Tag).where(Tag.name==name))
  if not t:t=Tag(name=name);db.add(t);db.flush()
  if not db.get(DocumentTag,{"document_id":d.id,"tag_id":t.id}):db.add(DocumentTag(document_id=d.id,tag_id=t.id))
 try:thumbnail(dest,mime,PREV/f"{v.id}.jpg")
 except Exception:pass

 item=DocumentIntakeItem(
  source=source,source_key=str(p),original_name=p.name,sha256=sh,status="imported",document_id=d.id,
  detected_title=meta["title"],detected_category=meta["category"],detected_subtype=meta["subtype"],detected_country=meta["country"],
  detected_issuer=meta["issuer"],detected_number=meta["document_number"],detected_issue_date=meta["issue_date"],detected_expiry_date=meta["expiry_date"],
  extracted_json=json.dumps({"confidence":meta["confidence"],"canonical_filename":canonical,"drive_file_id":(p.name.split("__",2)[1] if source=="google_drive" and p.name.startswith("gdrive__") and "__" in p.name else None)},ensure_ascii=False),
  processed_at=datetime.utcnow()
 )
 db.add(item);st.items_imported+=1;st.last_success_at=datetime.utcnow()
 if person_id:
  db.add(Audit(action="document.intake.person_matched",object_type="document",object_id=d.id,detail=person_id))
 db.add(Audit(action="document.intake.import",object_type="document",object_id=d.id,detail=f"{source}:{p.name} -> {canonical}"))
 db.commit()

while True:
 try:
  with SessionLocal() as db:
   for source,folder in SOURCES:
    st=source_state(db,source);st.last_scan_at=datetime.utcnow();db.commit()
    for p in sorted(x for x in folder.iterdir() if x.is_file() and not x.name.startswith(".")):
     try:handle(db,source,p)
     except Exception as e:
      db.rollback()
      st=source_state(db,source);st.last_error=str(e)[:1000];db.commit()
      print("document-intake:",source,p.name,e,flush=True)
 except Exception as e:print("document-intake-loop:",e,flush=True)
 time.sleep(int(os.getenv("DOCUMENT_INTAKE_INTERVAL","60")))

import hashlib,json,os,shutil,time,uuid
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal,ARCHIVE_ROOT
from .models import Document,DocumentVersion,DocumentIntakeItem,DocumentSourceState,Audit

DOCS=ARCHIVE_ROOT/"documents"
SOURCES=[("local",ARCHIVE_ROOT/"intake"),("google_drive",ARCHIVE_ROOT/"drive-inbox")]
ALLOWED={"application/pdf","image/jpeg","image/png","image/webp","image/tiff"}
for _,p in SOURCES:p.mkdir(parents=True,exist_ok=True)

def sha256(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()

def original_name(source,p):
 n=p.name
 if source=="google_drive" and n.startswith("gdrive__") and n.count("__")>=2:return n.split("__",2)[2]
 if source=="local" and "__" in n:
  a,b=n.split("__",1)
  if len(a)>=30:return b
 return n

def source_state(db,name):
 x=db.scalar(select(DocumentSourceState).where(DocumentSourceState.source==name))
 if not x:x=DocumentSourceState(source=name);db.add(x);db.flush()
 return x

def handle(db,source,p):
 from .services import detected_mime
 st=source_state(db,source);st.items_seen+=1
 key=str(p)
 if db.scalar(select(DocumentIntakeItem).where(DocumentIntakeItem.source==source,DocumentIntakeItem.source_key==key,DocumentIntakeItem.status.in_(["imported","duplicate"]))):return
 mime=detected_mime(p)
 if mime not in ALLOWED:
  db.add(DocumentIntakeItem(source=source,source_key=key,original_name=p.name,sha256="",status="rejected",error="unsupported file type",processed_at=datetime.utcnow()));db.commit()
  if source!="google_drive":p.unlink(missing_ok=True)
  return
 sh=sha256(p); prior=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sh))
 if prior:
  st.duplicates_ignored+=1
  db.add(DocumentIntakeItem(source=source,source_key=key,original_name=original_name(source,p),sha256=sh,status="duplicate",document_id=prior.document_id,processed_at=datetime.utcnow()))
  db.commit()
  if source!="google_drive":p.unlink(missing_ok=True)
  return
 name=original_name(source,p)
 title=Path(name).stem.replace("_"," ").strip() or "Untitled"
 d=Document(title=title,category="other",notes=f"Imported from {source}. Original filename: {name}")
 db.add(d);db.flush()
 ext=Path(name).suffix.lower()[:15];stored=f"{d.id}/v1-{uuid.uuid4()}{ext}"
 dest=DOCS/stored;dest.parent.mkdir(parents=True,exist_ok=True)
 if source=="google_drive":
  try:os.link(p,dest)
  except Exception:shutil.copy2(p,dest)
 else:shutil.move(p,dest)
 v=DocumentVersion(document_id=d.id,version=1,kind="original",original_name=name,stored_name=stored,mime_type=mime,size=dest.stat().st_size,sha256=sh,ocr_status="pending")
 db.add(v);db.flush()
 fid=p.name.split("__",2)[1] if source=="google_drive" and p.name.startswith("gdrive__") and p.name.count("__")>=2 else None
 db.add(DocumentIntakeItem(source=source,source_key=key,original_name=name,sha256=sh,status="imported",document_id=d.id,detected_title=title,detected_category="other",extracted_json=json.dumps({"drive_file_id":fid,"mode":"safe-import"},ensure_ascii=False),processed_at=datetime.utcnow()))
 db.add(Audit(action="document.intake.import",object_type="document",object_id=d.id,detail=f"{source}:{name}"))
 st.items_imported+=1;st.last_success_at=datetime.utcnow();db.commit()

while True:
 try:
  with SessionLocal() as db:
   for source,folder in SOURCES:
    st=source_state(db,source);st.last_scan_at=datetime.utcnow();db.commit()
    for p in sorted(x for x in folder.iterdir() if x.is_file() and not x.name.startswith(".")):
     try:handle(db,source,p)
     except Exception as e:
      db.rollback();st=source_state(db,source);st.last_error=str(e)[:1000];db.commit();print("document-intake:",source,p.name,e,flush=True)
 except Exception as e:print("document-intake-loop:",e,flush=True)
 time.sleep(int(os.getenv("DOCUMENT_INTAKE_INTERVAL","10")))

import hashlib,uuid,shutil
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT
from .auth import current_user,csrf_guard
from .models import Document,DocumentVersion,Audit
from .services import detected_mime
r=APIRouter(prefix="/api/import",dependencies=[Depends(current_user),Depends(csrf_guard)])
IMPORT=ARCHIVE_ROOT/"import";DOCS=ARCHIVE_ROOT/"documents";IMPORT.mkdir(parents=True,exist_ok=True)
ALLOWED={"application/pdf","image/jpeg","image/png","image/webp","image/tiff"}
def sha256(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
@r.get("/queue")
def queue():
 out=[]
 for p in sorted(x for x in IMPORT.iterdir() if x.is_file()):
  out.append({"name":p.name,"bytes":p.stat().st_size,"mime":detected_mime(p)})
 return out
@r.post("/process")
def process(db:Session=Depends(get_db)):
 ok=[];skip=[];bad=[]
 for p in sorted(x for x in IMPORT.iterdir() if x.is_file()):
  mime=detected_mime(p)
  if mime not in ALLOWED: bad.append({"name":p.name,"reason":"unsupported"});continue
  sh=sha256(p)
  if db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sh)):
   skip.append({"name":p.name,"reason":"duplicate"});continue
  d=Document(title=p.stem,category="other",notes="Bulk import");db.add(d);db.flush()
  ext=p.suffix.lower()[:15];stored=f"{d.id}/v1-{uuid.uuid4()}{ext}";dest=DOCS/stored;dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(p),str(dest))
  v=DocumentVersion(document_id=d.id,version=1,kind="original",original_name=p.name,stored_name=stored,mime_type=mime,size=dest.stat().st_size,sha256=sh);db.add(v)
  db.add(Audit(action="bulk.import",object_type="document",object_id=d.id,detail=p.name));ok.append({"id":d.id,"name":p.name})
 db.commit();return {"imported":ok,"duplicates":skip,"rejected":bad}

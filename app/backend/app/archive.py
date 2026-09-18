import hashlib,uuid,zipfile,io
from pathlib import Path
from datetime import date,timedelta
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form,Query
from fastapi.responses import FileResponse,StreamingResponse
from sqlalchemy import select,or_,func
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT,MAX_UPLOAD
from .auth import current_user,csrf_guard
from .models import *
from .schemas import *
from .services import extract_text,thumbnail,safe_name,detected_mime
r=APIRouter(prefix="/api/archive",dependencies=[Depends(current_user),Depends(csrf_guard)])
DOCS=ARCHIVE_ROOT/"documents"; PREV=ARCHIVE_ROOT/"previews"; EXPORT=ARCHIVE_ROOT/"exports"
for x in (DOCS,PREV,EXPORT):x.mkdir(parents=True,exist_ok=True)
def log(db,a,t,i=None,d=None):db.add(Audit(action=a,object_type=t,object_id=i,detail=d))
def copyhash(f,d):
 h=hashlib.sha256();n=0
 with d.open("wb") as o:
  while b:=f.read(1048576):
   n+=len(b)
   if n>MAX_UPLOAD:d.unlink(missing_ok=True);raise HTTPException(413,"File too large")
   h.update(b);o.write(b)
 return h.hexdigest(),n
def dj(x):return {k:getattr(x,k) for k in ("id","title","category","subtype","person_id","case_id","country","issuer","document_number","issue_date","expiry_date","notes","favorite","deleted","created_at","updated_at")}
@r.post("/people")
def person(x:PersonCreate,db:Session=Depends(get_db)):p=Person(**x.model_dump());db.add(p);db.flush();log(db,"create","person",p.id);db.commit();return {"id":p.id}
@r.get("/people")
def people(db:Session=Depends(get_db)):return [{"id":x.id,"name":x.name,"relation":x.relation} for x in db.scalars(select(Person).order_by(Person.name))]
@r.post("/cases")
def case(x:CaseCreate,db:Session=Depends(get_db)):c=Case(**x.model_dump());db.add(c);db.flush();log(db,"create","case",c.id);db.commit();return {"id":c.id}
@r.get("/cases")
def cases(db:Session=Depends(get_db)):return [{"id":x.id,"title":x.title,"status":x.status} for x in db.scalars(select(Case).order_by(Case.created_at.desc()))]
@r.post("/documents")
def create(file:UploadFile=File(...),title:str=Form(...),category:str=Form("other"),subtype:str|None=Form(None),person_id:str|None=Form(None),case_id:str|None=Form(None),country:str|None=Form(None),issuer:str|None=Form(None),document_number:str|None=Form(None),issue_date:date|None=Form(None),expiry_date:date|None=Form(None),notes:str|None=Form(None),kind:str=Form("original"),tags:str|None=Form(None),db:Session=Depends(get_db)):
 tmp=DOCS/f".tmp-{uuid.uuid4()}";sha,size=copyhash(file.file,tmp);dup=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sha))
 if dup:tmp.unlink(missing_ok=True);raise HTTPException(409,{"duplicate_of":dup.document_id})
 mime=detected_mime(tmp)
 if mime!="application/pdf" and not mime.startswith("image/"):tmp.unlink(missing_ok=True);raise HTTPException(415,"Only PDF and image files are allowed")
 d=Document(title=title,category=category,subtype=subtype,person_id=person_id or None,case_id=case_id or None,country=country,issuer=issuer,document_number=document_number,issue_date=issue_date,expiry_date=expiry_date,notes=notes);db.add(d);db.flush()
 ext=Path(file.filename or "").suffix.lower()[:15];name=f"{d.id}/v1-{uuid.uuid4()}{ext}";target=DOCS/name;target.parent.mkdir(parents=True,exist_ok=True);tmp.replace(target)
 v=DocumentVersion(document_id=d.id,version=1,kind=kind,original_name=file.filename or "file",stored_name=name,mime_type=mime,size=size,sha256=sha);db.add(v);db.flush()
 for n in [z.strip().lower() for z in (tags or "").split(",") if z.strip()]:
  t=db.scalar(select(Tag).where(Tag.name==n)) or Tag(name=n);db.add(t);db.flush();db.add(DocumentTag(document_id=d.id,tag_id=t.id))
 log(db,"upload","document",d.id,file.filename);db.commit();return {"id":d.id,"version":1,"sha256":sha,"ocr":"pending"}
@r.post("/documents/{did}/versions")
def version(did:str,file:UploadFile=File(...),kind:str=Form("updated"),db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d or d.deleted:raise HTTPException(404)
 tmp=DOCS/f".tmp-{uuid.uuid4()}";sha,size=copyhash(file.file,tmp);dup=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sha))
 if dup:tmp.unlink(missing_ok=True);raise HTTPException(409,{"duplicate_of":dup.document_id})
 mime=detected_mime(tmp)
 if mime!="application/pdf" and not mime.startswith("image/"):tmp.unlink(missing_ok=True);raise HTTPException(415,"Only PDF and image files are allowed")
 n=(db.scalar(select(func.max(DocumentVersion.version)).where(DocumentVersion.document_id==did)) or 0)+1;ext=Path(file.filename or "").suffix.lower()[:15];name=f"{did}/v{n}-{uuid.uuid4()}{ext}";p=DOCS/name;p.parent.mkdir(parents=True,exist_ok=True);tmp.replace(p)
 v=DocumentVersion(document_id=did,version=n,kind=kind,original_name=file.filename or "file",stored_name=name,mime_type=mime,size=size,sha256=sha);db.add(v);db.flush();log(db,"version.add","document",did,str(n));db.commit();return {"version":n,"ocr":"pending"}
@r.get("/documents")
def docs(q:str|None=None,category:str|None=None,person_id:str|None=None,case_id:str|None=None,deleted:bool=False,favorite:bool|None=None,limit:int=Query(100,le=500),db:Session=Depends(get_db)):
 s=select(Document).where(Document.deleted==deleted)
 if q:
  x=f"%{q}%";ocr_ids=select(DocumentVersion.document_id).where(DocumentVersion.ocr_text.ilike(x));tag_ids=select(DocumentTag.document_id).join(Tag,Tag.id==DocumentTag.tag_id).where(Tag.name.ilike(x));s=s.where(or_(Document.title.ilike(x),Document.notes.ilike(x),Document.document_number.ilike(x),Document.issuer.ilike(x),Document.id.in_(ocr_ids),Document.id.in_(tag_ids)))
 if category:s=s.where(Document.category==category)
 if person_id:s=s.where(Document.person_id==person_id)
 if case_id:s=s.where(Document.case_id==case_id)
 if favorite is not None:s=s.where(Document.favorite==favorite)
 return [dj(x) for x in db.scalars(s.order_by(Document.created_at.desc()).limit(limit))]
@r.get("/documents/{did}")
def detail(did:str,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404)
 vs=[{"id":v.id,"version":v.version,"kind":v.kind,"name":v.original_name,"mime":v.mime_type,"size":v.size,"sha256":v.sha256,"ocr_status":v.ocr_status,"ocr_text":v.ocr_text} for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==did).order_by(DocumentVersion.version.desc()))]
 tags=[x.name for x in db.scalars(select(Tag).join(DocumentTag,Tag.id==DocumentTag.tag_id).where(DocumentTag.document_id==did))]
 rel=[{"id":x.id,"target_id":x.target_id,"relation":x.relation} for x in db.scalars(select(Relation).where(Relation.source_id==did))]
 return {**dj(d),"versions":vs,"tags":tags,"relations":rel}
@r.patch("/documents/{did}")
def patch(did:str,x:DocumentPatch,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404)
 for k,v in x.model_dump(exclude_unset=True).items():setattr(d,k,v)
 log(db,"update","document",did);db.commit();return dj(d)
@r.get("/versions/{vid}/download")
def download(vid:str,db:Session=Depends(get_db)):
 v=db.get(DocumentVersion,vid)
 if not v or not (p:=DOCS/v.stored_name).exists():raise HTTPException(404)
 log(db,"download","document",v.document_id,v.original_name);db.commit();return FileResponse(p,media_type=v.mime_type,filename=v.original_name)
@r.get("/versions/{vid}/preview")
def preview(vid:str,db:Session=Depends(get_db)):
 v=db.get(DocumentVersion,vid);p=PREV/f"{vid}.jpg"
 if not v or not p.exists():raise HTTPException(404)
 return FileResponse(p,media_type="image/jpeg")
@r.post("/documents/{did}/relations")
def relation(did:str,x:RelationCreate,db:Session=Depends(get_db)):
 if not db.get(Document,did) or not db.get(Document,x.target_id):raise HTTPException(404)
 z=Relation(source_id=did,target_id=x.target_id,relation=x.relation);db.add(z);log(db,"relation.add","document",did,x.relation);db.commit();return {"id":z.id}
@r.post("/documents/{did}/reminders")
def reminder(did:str,remind_on:date=Form(...),note:str|None=Form(None),db:Session=Depends(get_db)):
 if not db.get(Document,did):raise HTTPException(404)
 z=Reminder(document_id=did,remind_on=remind_on,note=note);db.add(z);db.commit();return {"id":z.id}
@r.get("/reminders")
def reminders(db:Session=Depends(get_db)):return [{"id":x.id,"document_id":x.document_id,"remind_on":x.remind_on,"note":x.note,"done":x.done} for x in db.scalars(select(Reminder).where(Reminder.done==False).order_by(Reminder.remind_on))]
@r.get("/export")
def export(ids:str,db:Session=Depends(get_db)):
 wanted=[x for x in ids.split(",") if x];buf=io.BytesIO()
 with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
  for did in wanted:
   d=db.get(Document,did)
   if not d or d.deleted:continue
   for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==did)):
    p=DOCS/v.stored_name
    if p.exists():z.write(p,f"{safe_name(d.title)}/v{v.version}-{safe_name(v.original_name)}")
 buf.seek(0);log(db,"export","package",None,",".join(wanted));db.commit();return StreamingResponse(buf,media_type="application/zip",headers={"Content-Disposition":"attachment; filename=hossein-hub-export.zip"})
@r.delete("/documents/{did}")
def trash(did:str,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404)
 d.deleted=True;log(db,"trash","document",did);db.commit();return {"status":"trashed"}
@r.post("/documents/{did}/restore")
def restore(did:str,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d:raise HTTPException(404)
 d.deleted=False;log(db,"restore","document",did);db.commit();return {"status":"restored"}
@r.get("/expiring")
def expiring(days:int=90,db:Session=Depends(get_db)):
 end=date.today()+timedelta(days=days);return [dj(x) for x in db.scalars(select(Document).where(Document.deleted==False,Document.expiry_date!=None,Document.expiry_date<=end).order_by(Document.expiry_date))]
@r.get("/dashboard")
def dashboard(db:Session=Depends(get_db)):
 return {"documents":db.scalar(select(func.count()).select_from(Document).where(Document.deleted==False)),"trash":db.scalar(select(func.count()).select_from(Document).where(Document.deleted==True)),"storage_bytes":db.scalar(select(func.coalesce(func.sum(DocumentVersion.size),0))),"people":db.scalar(select(func.count()).select_from(Person)),"cases":db.scalar(select(func.count()).select_from(Case)),"reminders":db.scalar(select(func.count()).select_from(Reminder).where(Reminder.done==False))}
@r.get("/audit")
def audit(limit:int=Query(100,le=500),db:Session=Depends(get_db)):return [{"action":x.action,"type":x.object_type,"object_id":x.object_id,"detail":x.detail,"at":x.at} for x in db.scalars(select(Audit).order_by(Audit.at.desc()).limit(limit))]

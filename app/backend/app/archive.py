import hashlib,uuid,shutil
from pathlib import Path
from datetime import date,timedelta
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form,Query
from fastapi.responses import FileResponse
from sqlalchemy import select,or_,func
from sqlalchemy.orm import Session
from .core import get_db,require_key,ARCHIVE_ROOT,MAX_UPLOAD
from .models import Person,Case,Document,DocumentVersion,Relation,Audit
from .schemas import PersonCreate,CaseCreate,RelationCreate,DocumentPatch
r=APIRouter(prefix="/api/archive",dependencies=[Depends(require_key)])
DOCS=ARCHIVE_ROOT/"documents"; TRASH=ARCHIVE_ROOT/"trash"
DOCS.mkdir(parents=True,exist_ok=True); TRASH.mkdir(parents=True,exist_ok=True)
def log(db,a,t,i=None,d=None): db.add(Audit(action=a,object_type=t,object_id=i,detail=d))
def digest_copy(f,dest):
    h=hashlib.sha256(); n=0
    with dest.open("wb") as o:
        while b:=f.read(1024*1024):
            n+=len(b)
            if n>MAX_UPLOAD: dest.unlink(missing_ok=True); raise HTTPException(413,"File too large")
            h.update(b); o.write(b)
    return h.hexdigest(),n
def doc_json(x): return {k:getattr(x,k) for k in ("id","title","category","subtype","person_id","case_id","country","issuer","document_number","issue_date","expiry_date","notes","favorite","deleted","created_at","updated_at")}
@r.post("/people")
def person(x:PersonCreate,db:Session=Depends(get_db)): p=Person(**x.model_dump()); db.add(p);db.flush();log(db,"create","person",p.id);db.commit();return {"id":p.id}
@r.get("/people")
def people(db:Session=Depends(get_db)): return [{"id":x.id,"name":x.name,"relation":x.relation} for x in db.scalars(select(Person).order_by(Person.name))]
@r.post("/cases")
def case(x:CaseCreate,db:Session=Depends(get_db)): c=Case(**x.model_dump());db.add(c);db.flush();log(db,"create","case",c.id);db.commit();return {"id":c.id}
@r.get("/cases")
def cases(db:Session=Depends(get_db)): return [{"id":x.id,"title":x.title,"status":x.status} for x in db.scalars(select(Case).order_by(Case.created_at.desc()))]
@r.post("/documents")
def create_document(file:UploadFile=File(...),title:str=Form(...),category:str=Form("other"),subtype:str|None=Form(None),person_id:str|None=Form(None),case_id:str|None=Form(None),country:str|None=Form(None),issuer:str|None=Form(None),document_number:str|None=Form(None),issue_date:date|None=Form(None),expiry_date:date|None=Form(None),notes:str|None=Form(None),kind:str=Form("original"),db:Session=Depends(get_db)):
    tmp=DOCS/f".tmp-{uuid.uuid4()}"; sha,size=digest_copy(file.file,tmp)
    dup=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sha))
    if dup: tmp.unlink(missing_ok=True); raise HTTPException(409,{"duplicate_of":dup.document_id,"version_id":dup.id})
    d=Document(title=title,category=category,subtype=subtype,person_id=person_id or None,case_id=case_id or None,country=country,issuer=issuer,document_number=document_number,issue_date=issue_date,expiry_date=expiry_date,notes=notes);db.add(d);db.flush()
    ext=Path(file.filename or "").suffix.lower()[:20]; name=f"{d.id}/v1-{uuid.uuid4()}{ext}"; target=DOCS/name;target.parent.mkdir(parents=True,exist_ok=True);tmp.replace(target)
    v=DocumentVersion(document_id=d.id,version=1,kind=kind,original_name=file.filename or "file",stored_name=name,mime_type=file.content_type,size=size,sha256=sha);db.add(v);log(db,"upload","document",d.id,file.filename);db.commit();return {"id":d.id,"version":1,"sha256":sha}
@r.post("/documents/{did}/versions")
def add_version(did:str,file:UploadFile=File(...),kind:str=Form("updated"),db:Session=Depends(get_db)):
    d=db.get(Document,did)
    if not d or d.deleted: raise HTTPException(404)
    tmp=DOCS/f".tmp-{uuid.uuid4()}";sha,size=digest_copy(file.file,tmp)
    dup=db.scalar(select(DocumentVersion).where(DocumentVersion.sha256==sha))
    if dup: tmp.unlink(missing_ok=True);raise HTTPException(409,{"duplicate_of":dup.document_id})
    last=db.scalar(select(func.max(DocumentVersion.version)).where(DocumentVersion.document_id==did)) or 0;n=last+1;ext=Path(file.filename or "").suffix.lower()[:20];name=f"{did}/v{n}-{uuid.uuid4()}{ext}";target=DOCS/name;target.parent.mkdir(parents=True,exist_ok=True);tmp.replace(target)
    v=DocumentVersion(document_id=did,version=n,kind=kind,original_name=file.filename or "file",stored_name=name,mime_type=file.content_type,size=size,sha256=sha);db.add(v);log(db,"version.add","document",did,str(n));db.commit();return {"version":n,"sha256":sha}
@r.get("/documents")
def documents(q:str|None=None,category:str|None=None,person_id:str|None=None,case_id:str|None=None,deleted:bool=False,favorite:bool|None=None,limit:int=Query(100,le=500),db:Session=Depends(get_db)):
    s=select(Document).where(Document.deleted==deleted)
    if q:
        x=f"%{q}%";s=s.where(or_(Document.title.ilike(x),Document.notes.ilike(x),Document.document_number.ilike(x),Document.issuer.ilike(x)))
    if category:s=s.where(Document.category==category)
    if person_id:s=s.where(Document.person_id==person_id)
    if case_id:s=s.where(Document.case_id==case_id)
    if favorite is not None:s=s.where(Document.favorite==favorite)
    return [doc_json(x) for x in db.scalars(s.order_by(Document.created_at.desc()).limit(limit))]
@r.get("/documents/{did}")
def get_document(did:str,db:Session=Depends(get_db)):
    d=db.get(Document,did)
    if not d:raise HTTPException(404)
    versions=[{"id":v.id,"version":v.version,"kind":v.kind,"name":v.original_name,"mime":v.mime_type,"size":v.size,"sha256":v.sha256,"ocr_status":v.ocr_status} for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==did).order_by(DocumentVersion.version.desc()))]
    return {**doc_json(d),"versions":versions}
@r.patch("/documents/{did}")
def patch(did:str,x:DocumentPatch,db:Session=Depends(get_db)):
    d=db.get(Document,did)
    if not d:raise HTTPException(404)
    for k,v in x.model_dump(exclude_unset=True).items():setattr(d,k,v)
    log(db,"update","document",did);db.commit();return doc_json(d)
@r.get("/versions/{vid}/download")
def download(vid:str,db:Session=Depends(get_db)):
    v=db.get(DocumentVersion,vid)
    if not v:raise HTTPException(404)
    d=db.get(Document,v.document_id)
    if not d or d.deleted:raise HTTPException(404)
    p=DOCS/v.stored_name
    if not p.exists():raise HTTPException(410)
    log(db,"download","document",d.id,v.original_name);db.commit();return FileResponse(p,media_type=v.mime_type,filename=v.original_name)
@r.post("/documents/{did}/relations")
def relate(did:str,x:RelationCreate,db:Session=Depends(get_db)):
    if not db.get(Document,did) or not db.get(Document,x.target_id):raise HTTPException(404)
    z=Relation(source_id=did,target_id=x.target_id,relation=x.relation);db.add(z);log(db,"relation.add","document",did,x.relation);db.commit();return {"id":z.id}
@r.delete("/documents/{did}")
def trash(did:str,db:Session=Depends(get_db)):
    d=db.get(Document,did)
    if not d or d.deleted:raise HTTPException(404)
    d.deleted=True;log(db,"trash","document",did);db.commit();return {"status":"trashed"}
@r.post("/documents/{did}/restore")
def restore(did:str,db:Session=Depends(get_db)):
    d=db.get(Document,did)
    if not d or not d.deleted:raise HTTPException(404)
    d.deleted=False;log(db,"restore","document",did);db.commit();return {"status":"restored"}
@r.get("/expiring")
def expiring(days:int=90,db:Session=Depends(get_db)):
    end=date.today()+timedelta(days=days);return [doc_json(x) for x in db.scalars(select(Document).where(Document.deleted==False,Document.expiry_date!=None,Document.expiry_date<=end).order_by(Document.expiry_date))]
@r.get("/dashboard")
def dashboard(db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(Document).where(Document.deleted==False));trash=db.scalar(select(func.count()).select_from(Document).where(Document.deleted==True));size=db.scalar(select(func.coalesce(func.sum(DocumentVersion.size),0)));people=db.scalar(select(func.count()).select_from(Person));cases=db.scalar(select(func.count()).select_from(Case))
    return {"documents":total,"trash":trash,"storage_bytes":size,"people":people,"cases":cases}
@r.get("/audit")
def audit(limit:int=Query(100,le=500),db:Session=Depends(get_db)):return [{"action":x.action,"type":x.object_type,"object_id":x.object_id,"detail":x.detail,"at":x.at} for x in db.scalars(select(Audit).order_by(Audit.at.desc()).limit(limit))]

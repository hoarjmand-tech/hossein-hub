import os, hashlib, shutil, uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, String, Text, Date, DateTime, Boolean, ForeignKey, select, or_, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

DB=os.environ["DATABASE_URL"]
ROOT=Path(os.getenv("ARCHIVE_ROOT","/archive")).resolve()
DOCS=ROOT/"documents"; TRASH=ROOT/"trash"; IMPORT=ROOT/"import"; EXPORTS=ROOT/"exports"
for p in (DOCS,TRASH,IMPORT,EXPORTS): p.mkdir(parents=True,exist_ok=True)
MAX=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
API_KEY=os.environ["HUB_API_KEY"]
engine=create_engine(DB,pool_pre_ping=True)

class Base(DeclarativeBase): pass
class Person(Base):
    __tablename__="people"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    name:Mapped[str]=mapped_column(String(250),index=True)
    notes:Mapped[Optional[str]]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Case(Base):
    __tablename__="cases"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    title:Mapped[str]=mapped_column(String(300),index=True)
    status:Mapped[str]=mapped_column(String(50),default="active")
    notes:Mapped[Optional[str]]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Document(Base):
    __tablename__="documents"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    title:Mapped[str]=mapped_column(String(400),index=True)
    category:Mapped[str]=mapped_column(String(100),index=True)
    person_id:Mapped[Optional[str]]=mapped_column(ForeignKey("people.id"),index=True)
    case_id:Mapped[Optional[str]]=mapped_column(ForeignKey("cases.id"),index=True)
    country:Mapped[Optional[str]]=mapped_column(String(100))
    issuer:Mapped[Optional[str]]=mapped_column(String(250))
    document_number:Mapped[Optional[str]]=mapped_column(String(150),index=True)
    issue_date:Mapped[Optional[date]]=mapped_column(Date)
    expiry_date:Mapped[Optional[date]]=mapped_column(Date,index=True)
    tags:Mapped[Optional[str]]=mapped_column(Text)
    notes:Mapped[Optional[str]]=mapped_column(Text)
    original_name:Mapped[str]=mapped_column(String(500))
    stored_name:Mapped[str]=mapped_column(String(500),unique=True)
    mime_type:Mapped[Optional[str]]=mapped_column(String(200))
    size:Mapped[int]
    sha256:Mapped[str]=mapped_column(String(64),index=True)
    favorite:Mapped[bool]=mapped_column(Boolean,default=False)
    deleted:Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
class Audit(Base):
    __tablename__="audit"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    action:Mapped[str]=mapped_column(String(100),index=True)
    object_id:Mapped[Optional[str]]=mapped_column(String(36),index=True)
    detail:Mapped[Optional[str]]=mapped_column(Text)
    at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
Base.metadata.create_all(engine)

app=FastAPI(title="Hossein Hub Archive API",version="1.0.0")
def auth(x_api_key:str=Header(...)):
    if not __import__("hmac").compare_digest(x_api_key,API_KEY): raise HTTPException(401,"invalid API key")
def db():
    with Session(engine) as s: yield s
def audit(s,action,obj=None,detail=None):
    s.add(Audit(id=str(uuid.uuid4()),action=action,object_id=obj,detail=detail))

class PersonIn(BaseModel): name:str; notes:Optional[str]=None
class CaseIn(BaseModel): title:str; status:str="active"; notes:Optional[str]=None

@app.get("/health")
def health(): return {"status":"ok","service":"archive","time":datetime.utcnow().isoformat()+"Z"}

@app.post("/people",dependencies=[Depends(auth)])
def add_person(x:PersonIn,s:Session=Depends(db)):
    p=Person(id=str(uuid.uuid4()),**x.model_dump()); s.add(p); audit(s,"person.create",p.id); s.commit(); return {"id":p.id}
@app.get("/people",dependencies=[Depends(auth)])
def people(s:Session=Depends(db)): return [{"id":x.id,"name":x.name,"notes":x.notes} for x in s.scalars(select(Person).order_by(Person.name))]

@app.post("/cases",dependencies=[Depends(auth)])
def add_case(x:CaseIn,s:Session=Depends(db)):
    c=Case(id=str(uuid.uuid4()),**x.model_dump()); s.add(c); audit(s,"case.create",c.id); s.commit(); return {"id":c.id}
@app.get("/cases",dependencies=[Depends(auth)])
def cases(s:Session=Depends(db)): return [{"id":x.id,"title":x.title,"status":x.status} for x in s.scalars(select(Case).order_by(Case.created_at.desc()))]

@app.post("/documents",dependencies=[Depends(auth)])
def upload(file:UploadFile=File(...),title:str=Form(...),category:str=Form("other"),person_id:Optional[str]=Form(None),case_id:Optional[str]=Form(None),country:Optional[str]=Form(None),issuer:Optional[str]=Form(None),document_number:Optional[str]=Form(None),issue_date:Optional[date]=Form(None),expiry_date:Optional[date]=Form(None),tags:Optional[str]=Form(None),notes:Optional[str]=Form(None),s:Session=Depends(db)):
    tmp=DOCS/f".upload-{uuid.uuid4()}"
    h=hashlib.sha256(); size=0
    with tmp.open("wb") as out:
        while chunk:=file.file.read(1024*1024):
            size+=len(chunk)
            if size>MAX: out.close(); tmp.unlink(missing_ok=True); raise HTTPException(413,"file too large")
            h.update(chunk); out.write(chunk)
    digest=h.hexdigest()
    duplicate=s.scalar(select(Document).where(Document.sha256==digest,Document.deleted==False))
    if duplicate: tmp.unlink(missing_ok=True); raise HTTPException(409,detail={"message":"duplicate","document_id":duplicate.id})
    ext=Path(file.filename or "").suffix.lower()[:20]
    did=str(uuid.uuid4()); stored=f"{did}{ext}"; dest=DOCS/stored; tmp.replace(dest)
    d=Document(id=did,title=title,category=category,person_id=person_id or None,case_id=case_id or None,country=country,issuer=issuer,document_number=document_number,issue_date=issue_date,expiry_date=expiry_date,tags=tags,notes=notes,original_name=file.filename or "file",stored_name=stored,mime_type=file.content_type,size=size,sha256=digest)
    s.add(d); audit(s,"document.upload",did,file.filename); s.commit()
    return {"id":did,"sha256":digest,"size":size}

def dto(d): return {k:getattr(d,k) for k in ("id","title","category","person_id","case_id","country","issuer","document_number","issue_date","expiry_date","tags","notes","original_name","mime_type","size","sha256","favorite","deleted","created_at")}
@app.get("/documents",dependencies=[Depends(auth)])
def documents(q:Optional[str]=None,category:Optional[str]=None,person_id:Optional[str]=None,case_id:Optional[str]=None,deleted:bool=False,limit:int=Query(100,le=500),s:Session=Depends(db)):
    st=select(Document).where(Document.deleted==deleted)
    if q:
        x=f"%{q}%"; st=st.where(or_(Document.title.ilike(x),Document.tags.ilike(x),Document.notes.ilike(x),Document.document_number.ilike(x)))
    if category: st=st.where(Document.category==category)
    if person_id: st=st.where(Document.person_id==person_id)
    if case_id: st=st.where(Document.case_id==case_id)
    return [dto(x) for x in s.scalars(st.order_by(Document.created_at.desc()).limit(limit))]
@app.get("/documents/{did}",dependencies=[Depends(auth)])
def document(did:str,s:Session=Depends(db)):
    d=s.get(Document,did)
    if not d: raise HTTPException(404)
    return dto(d)
@app.get("/documents/{did}/download",dependencies=[Depends(auth)])
def download(did:str,s:Session=Depends(db)):
    d=s.get(Document,did)
    if not d or d.deleted: raise HTTPException(404)
    p=DOCS/d.stored_name
    if not p.exists(): raise HTTPException(410,"stored file missing")
    audit(s,"document.download",did); s.commit()
    return FileResponse(p,media_type=d.mime_type,filename=d.original_name)
@app.post("/documents/{did}/favorite",dependencies=[Depends(auth)])
def favorite(did:str,s:Session=Depends(db)):
    d=s.get(Document,did)
    if not d: raise HTTPException(404)
    d.favorite=not d.favorite; audit(s,"document.favorite",did,str(d.favorite)); s.commit(); return {"favorite":d.favorite}
@app.delete("/documents/{did}",dependencies=[Depends(auth)])
def trash(did:str,s:Session=Depends(db)):
    d=s.get(Document,did)
    if not d or d.deleted: raise HTTPException(404)
    src=DOCS/d.stored_name; dst=TRASH/d.stored_name
    if src.exists(): shutil.move(src,dst)
    d.deleted=True; audit(s,"document.trash",did); s.commit(); return {"status":"trashed"}
@app.post("/documents/{did}/restore",dependencies=[Depends(auth)])
def restore(did:str,s:Session=Depends(db)):
    d=s.get(Document,did)
    if not d or not d.deleted: raise HTTPException(404)
    src=TRASH/d.stored_name; dst=DOCS/d.stored_name
    if not src.exists(): raise HTTPException(410,"trash file missing")
    shutil.move(src,dst); d.deleted=False; audit(s,"document.restore",did); s.commit(); return {"status":"restored"}
@app.get("/dashboard",dependencies=[Depends(auth)])
def dashboard(s:Session=Depends(db)):
    total=s.scalar(select(func.count()).select_from(Document).where(Document.deleted==False))
    trash_n=s.scalar(select(func.count()).select_from(Document).where(Document.deleted==True))
    size=s.scalar(select(func.coalesce(func.sum(Document.size),0)).where(Document.deleted==False))
    exp=s.scalar(select(func.count()).select_from(Document).where(Document.deleted==False,Document.expiry_date!=None,Document.expiry_date<=date.today()))
    return {"documents":total,"trash":trash_n,"bytes":size,"expired":exp}
@app.get("/audit",dependencies=[Depends(auth)])
def audits(limit:int=Query(100,le=500),s:Session=Depends(db)):
    return [{"action":x.action,"object_id":x.object_id,"detail":x.detail,"at":x.at} for x in s.scalars(select(Audit).order_by(Audit.at.desc()).limit(limit))]

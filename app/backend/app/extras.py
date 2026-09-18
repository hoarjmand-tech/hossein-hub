import hashlib,secrets,io,zipfile
from datetime import datetime,timedelta
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Form
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT
from .auth import current_user
from .models import Document,DocumentVersion,ShareLink,Reminder,Audit
r=APIRouter()
DOCS=ARCHIVE_ROOT/"documents"
def hh(x):return hashlib.sha256(x.encode()).hexdigest()
@r.post("/api/archive/documents/{did}/share",dependencies=[Depends(current_user)])
def share(did:str,hours:int=Form(24),max_downloads:int=Form(1),db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d or d.deleted:raise HTTPException(404)
 raw=secrets.token_urlsafe(32);z=ShareLink(document_id=did,token_hash=hh(raw),expires_at=datetime.utcnow()+timedelta(hours=max(1,min(hours,168))),max_downloads=max(1,min(max_downloads,20)));db.add(z);db.add(Audit(action="share.create",object_type="document",object_id=did));db.commit();return {"token":raw,"expires_at":z.expires_at,"max_downloads":z.max_downloads}
@r.get("/s/{token}")
def shared(token:str,db:Session=Depends(get_db)):
 z=db.scalar(select(ShareLink).where(ShareLink.token_hash==hh(token)))
 if not z or not z.active or z.expires_at<datetime.utcnow() or z.downloads>=z.max_downloads:raise HTTPException(404,"Link expired")
 d=db.get(Document,z.document_id);v=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==d.id).order_by(DocumentVersion.version.desc()))
 if not v or not (p:=DOCS/v.stored_name).exists():raise HTTPException(404)
 z.downloads+=1;db.add(Audit(action="share.download",object_type="document",object_id=d.id));db.commit();return FileResponse(p,media_type=v.mime_type,filename=v.original_name)
@r.post("/api/archive/reminders/{rid}/done",dependencies=[Depends(current_user)])
def reminder_done(rid:str,db:Session=Depends(get_db)):
 x=db.get(Reminder,rid)
 if not x:raise HTTPException(404)
 x.done=True;db.commit();return {"ok":True}

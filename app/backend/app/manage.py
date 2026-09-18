from datetime import date,timedelta,datetime
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form
from sqlalchemy import select,func,delete
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT
from .auth import current_user,csrf_guard
from .models import *
r=APIRouter(prefix="/api/manage",dependencies=[Depends(current_user),Depends(csrf_guard)])
@r.patch("/people/{pid}")
def person_update(pid:str,name:str=Form(...),relation:str|None=Form(None),notes:str|None=Form(None),db:Session=Depends(get_db)):
 x=db.get(Person,pid)
 if not x:raise HTTPException(404)
 x.name=name;x.relation=relation;x.notes=notes;db.add(Audit(action="update",object_type="person",object_id=pid));db.commit();return {"ok":True}
@r.delete("/people/{pid}")
def person_delete(pid:str,db:Session=Depends(get_db)):
 if db.scalar(select(func.count()).select_from(Document).where(Document.person_id==pid)):raise HTTPException(409,"Person has documents")
 x=db.get(Person,pid)
 if not x:raise HTTPException(404)
 db.delete(x);db.commit();return {"ok":True}
@r.patch("/cases/{cid}")
def case_update(cid:str,title:str=Form(...),status:str=Form("active"),notes:str|None=Form(None),db:Session=Depends(get_db)):
 x=db.get(Case,cid)
 if not x:raise HTTPException(404)
 x.title=title;x.status=status;x.notes=notes;db.commit();return {"ok":True}
@r.delete("/cases/{cid}")
def case_delete(cid:str,db:Session=Depends(get_db)):
 if db.scalar(select(func.count()).select_from(Document).where(Document.case_id==cid)):raise HTTPException(409,"Case has documents")
 x=db.get(Case,cid)
 if not x:raise HTTPException(404)
 db.delete(x);db.commit();return {"ok":True}
@r.delete("/trash/{did}/purge")
def purge(did:str,db:Session=Depends(get_db)):
 d=db.get(Document,did)
 if not d or not d.deleted:raise HTTPException(404)
 for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==did)):
  (ARCHIVE_ROOT/"documents"/v.stored_name).unlink(missing_ok=True);(ARCHIVE_ROOT/"previews"/f"{v.id}.jpg").unlink(missing_ok=True)
 db.execute(delete(DocumentTag).where(DocumentTag.document_id==did));db.execute(delete(Relation).where((Relation.source_id==did)|(Relation.target_id==did)));db.execute(delete(Reminder).where(Reminder.document_id==did));db.execute(delete(ShareLink).where(ShareLink.document_id==did));db.execute(delete(DocumentVersion).where(DocumentVersion.document_id==did));db.delete(d);db.add(Audit(action="purge",object_type="document",object_id=did));db.commit();return {"ok":True}
@r.get("/notifications")
def notifications(db:Session=Depends(get_db)):
 today=date.today();limit=today+timedelta(days=30)
 existing={x.document_id for x in db.scalars(select(Notification).where(Notification.kind=="expiry",Notification.created_at>=datetime.utcnow()-timedelta(days=1)))}
 for d in db.scalars(select(Document).where(Document.deleted==False,Document.expiry_date!=None,Document.expiry_date<=limit)):
  if d.id not in existing:db.add(Notification(kind="expiry",title=f"انقضای {d.title}",body=f"تاریخ انقضا: {d.expiry_date}",document_id=d.id))
 db.commit()
 return [{"id":x.id,"kind":x.kind,"title":x.title,"body":x.body,"document_id":x.document_id,"read":x.read,"created_at":x.created_at} for x in db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(100))]
@r.post("/notifications/{nid}/read")
def mark_read(nid:str,db:Session=Depends(get_db)):
 x=db.get(Notification,nid)
 if not x:raise HTTPException(404)
 x.read=True;db.commit();return {"ok":True}

@r.post("/notifications/read-all")
def notifications_read_all(db:Session=Depends(get_db)):
 for x in db.scalars(select(Notification).where(Notification.read==False)):
  x.read=True
 db.commit();return {"ok":True}

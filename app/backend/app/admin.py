from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,ph,csrf_guard
from .models import User,Audit,SessionToken
r=APIRouter(prefix="/api/admin",dependencies=[Depends(current_user),Depends(csrf_guard)])
class UserCreate(BaseModel):
 username:str=Field(min_length=3,max_length=100);password:str=Field(min_length=12,max_length=200);is_admin:bool=False
class UserPatch(BaseModel):
 active:bool|None=None;is_admin:bool|None=None
class PasswordReset(BaseModel):
 password:str=Field(min_length=12,max_length=200)
def require_admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u
@r.get("/users")
def users(db:Session=Depends(get_db),u=Depends(require_admin)):
 return [{"id":x.id,"username":x.username,"is_admin":x.is_admin,"active":x.active,"created_at":x.created_at,"last_login":x.last_login} for x in db.scalars(select(User).order_by(User.created_at))]
@r.post("/users")
def add(x:UserCreate,db:Session=Depends(get_db),u=Depends(require_admin)):
 if db.scalar(select(User).where(User.username==x.username.strip())):raise HTTPException(409,"Username exists")
 z=User(username=x.username.strip(),password_hash=ph.hash(x.password),is_admin=x.is_admin,active=True);db.add(z);db.flush();db.add(Audit(action="user.create",object_type="user",object_id=z.id,detail=z.username));db.commit();return {"id":z.id}
@r.patch("/users/{uid}")
def patch(uid:str,x:UserPatch,db:Session=Depends(get_db),u=Depends(require_admin)):
 z=db.get(User,uid)
 if not z:raise HTTPException(404)
 changes=x.model_dump(exclude_unset=True)
 if ("active" in changes and changes["active"]==False) or ("is_admin" in changes and changes["is_admin"]==False):
  if z.is_admin and z.active:
   remaining=db.scalar(select(func.count()).select_from(User).where(User.is_admin==True,User.active==True,User.id!=z.id)) or 0
   if remaining<1:raise HTTPException(409,"At least one active admin is required")
 for k,v in changes.items():setattr(z,k,v)
 db.add(Audit(action="user.update",object_type="user",object_id=z.id,detail=z.username));db.commit();return {"ok":True}
@r.get("/stats")
def stats(db:Session=Depends(get_db),u=Depends(require_admin)):
 return {"users":db.scalar(select(func.count()).select_from(User)) or 0,"admins":db.scalar(select(func.count()).select_from(User).where(User.is_admin==True)) or 0}

@r.post("/users/{uid}/password-reset")
def password_reset(uid:str,x:PasswordReset,db:Session=Depends(get_db),u=Depends(require_admin)):
 z=db.get(User,uid)
 if not z:raise HTTPException(404)
 z.password_hash=ph.hash(x.password)
 db.query(SessionToken).filter(SessionToken.user_id==uid).delete(synchronize_session=False)
 db.add(Audit(action="user.password.reset",object_type="user",object_id=z.id,detail=f"reset by {u.username}"))
 db.commit()
 return {"ok":True}

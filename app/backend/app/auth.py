import hashlib,secrets
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel
from sqlalchemy import select,func,delete
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from .core import get_db
from .models import User,SessionToken,Audit
r=APIRouter(prefix="/api/auth");ph=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=4)
COOKIE="hub_session";TTL_DAYS=7
class Credentials(BaseModel):username:str;password:str
def h(x):return hashlib.sha256(x.encode()).hexdigest()
def current_user(request:Request,db:Session=Depends(get_db)):
 tok=request.cookies.get(COOKIE)
 if not tok:raise HTTPException(401,"Login required")
 s=db.scalar(select(SessionToken).where(SessionToken.token_hash==h(tok),SessionToken.expires_at>datetime.utcnow()))
 if not s:raise HTTPException(401,"Session expired")
 u=db.get(User,s.user_id)
 if not u or not u.active:raise HTTPException(401)
 return u
def csrf(request:Request,db:Session=Depends(get_db)):
 tok=request.cookies.get(COOKIE);c=request.headers.get("X-CSRF-Token","")
 if not tok or not c:raise HTTPException(403,"CSRF")
 s=db.scalar(select(SessionToken).where(SessionToken.token_hash==h(tok),SessionToken.expires_at>datetime.utcnow()))
 if not s or not secrets.compare_digest(s.csrf_hash,h(c)):raise HTTPException(403,"CSRF")
 return s
@r.get("/status")
def status(db:Session=Depends(get_db)):return {"setup_required":(db.scalar(select(func.count()).select_from(User)) or 0)==0}
@r.post("/setup")
def setup(x:Credentials,response:Response,db:Session=Depends(get_db)):
 if (db.scalar(select(func.count()).select_from(User)) or 0)>0:raise HTTPException(409,"Already configured")
 if len(x.username)<3 or len(x.password)<12:raise HTTPException(400,"Username >=3 and password >=12 required")
 u=User(username=x.username.strip(),password_hash=ph.hash(x.password));db.add(u);db.flush();return issue(u,response,db,"setup")
def issue(u,response,db,action):
 raw=secrets.token_urlsafe(48);c=secrets.token_urlsafe(32);s=SessionToken(user_id=u.id,token_hash=h(raw),csrf_hash=h(c),expires_at=datetime.utcnow()+timedelta(days=TTL_DAYS));db.add(s);u.last_login=datetime.utcnow();db.add(Audit(action=action,object_type="auth",object_id=u.id));db.commit();response.set_cookie(COOKIE,raw,httponly=True,samesite="strict",secure=False,max_age=TTL_DAYS*86400,path="/");return {"ok":True,"username":u.username,"csrf":c}
@r.post("/login")
def login(x:Credentials,response:Response,db:Session=Depends(get_db)):
 u=db.scalar(select(User).where(User.username==x.username.strip()))
 try:ok=bool(u and u.active and ph.verify(u.password_hash,x.password))
 except VerifyMismatchError:ok=False
 if not ok:raise HTTPException(401,"Invalid credentials")
 return issue(u,response,db,"login")
@r.get("/me")
def me(request:Request,db:Session=Depends(get_db)):
 u=current_user(request,db);tok=request.cookies.get(COOKIE);s=db.scalar(select(SessionToken).where(SessionToken.token_hash==h(tok)));c=secrets.token_urlsafe(32);s.csrf_hash=h(c);db.commit();return {"username":u.username,"admin":u.is_admin,"csrf":c}
@r.post("/logout")
def logout(request:Request,response:Response,db:Session=Depends(get_db)):
 tok=request.cookies.get(COOKIE)
 if tok:db.execute(delete(SessionToken).where(SessionToken.token_hash==h(tok)));db.commit()
 response.delete_cookie(COOKIE,path="/");return {"ok":True}

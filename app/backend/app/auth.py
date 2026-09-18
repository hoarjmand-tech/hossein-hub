import hashlib,secrets,time
from collections import defaultdict,deque
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel
from sqlalchemy import select,func,delete
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from .core import get_db
from .models import User,SessionToken,Audit
r=APIRouter(prefix="/api/auth");ph=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=4);COOKIE="hub_session";TTL_DAYS=7;attempts=defaultdict(deque)
class Credentials(BaseModel):username:str;password:str
class PasswordChange(BaseModel):current_password:str;new_password:str
def h(x):return hashlib.sha256(x.encode()).hexdigest()
def limited(ip):
 now=time.time();q=attempts[ip]
 while q and q[0]<now-900:q.popleft()
 if len(q)>=8:raise HTTPException(429,"Too many attempts")
 q.append(now)
def session(request,db):
 tok=request.cookies.get(COOKIE)
 if not tok:raise HTTPException(401,"Login required")
 s=db.scalar(select(SessionToken).where(SessionToken.token_hash==h(tok),SessionToken.expires_at>datetime.utcnow()))
 if not s:raise HTTPException(401,"Session expired")
 return s
def current_user(request:Request,db:Session=Depends(get_db)):
 s=session(request,db);u=db.get(User,s.user_id)
 if not u or not u.active:raise HTTPException(401)
 return u
def csrf_guard(request:Request,db:Session=Depends(get_db)):
 if request.method in ("GET","HEAD","OPTIONS"):return
 s=session(request,db);c=request.headers.get("X-CSRF-Token","")
 if not c or not secrets.compare_digest(s.csrf_hash,h(c)):raise HTTPException(403,"CSRF")
@r.get("/status")
def status(db:Session=Depends(get_db)):return {"setup_required":(db.scalar(select(func.count()).select_from(User)) or 0)==0}
def issue(u,response,db,action):
 raw=secrets.token_urlsafe(48);c=secrets.token_urlsafe(32);s=SessionToken(user_id=u.id,token_hash=h(raw),csrf_hash=h(c),expires_at=datetime.utcnow()+timedelta(days=TTL_DAYS));db.add(s);u.last_login=datetime.utcnow();db.add(Audit(action=action,object_type="auth",object_id=u.id));db.commit();response.set_cookie(COOKIE,raw,httponly=True,samesite="strict",secure=False,max_age=TTL_DAYS*86400,path="/");return {"ok":True,"username":u.username,"csrf":c}
@r.post("/setup")
def setup(x:Credentials,response:Response,db:Session=Depends(get_db)):
 if (db.scalar(select(func.count()).select_from(User)) or 0)>0:raise HTTPException(409)
 if len(x.username)<3 or len(x.password)<12:raise HTTPException(400,"Minimum password length is 12")
 u=User(username=x.username.strip(),password_hash=ph.hash(x.password));db.add(u);db.flush();return issue(u,response,db,"setup")
@r.post("/login")
def login(x:Credentials,request:Request,response:Response,db:Session=Depends(get_db)):
 limited(request.client.host if request.client else "unknown");u=db.scalar(select(User).where(User.username==x.username.strip()))
 try:ok=bool(u and u.active and ph.verify(u.password_hash,x.password))
 except VerifyMismatchError:ok=False
 if not ok:raise HTTPException(401,"Invalid credentials")
 attempts.pop(request.client.host if request.client else "unknown",None);return issue(u,response,db,"login")
@r.get("/me")
def me(request:Request,db:Session=Depends(get_db)):
 u=current_user(request,db);s=session(request,db);c=secrets.token_urlsafe(32);s.csrf_hash=h(c);db.commit();return {"username":u.username,"admin":u.is_admin,"csrf":c}
@r.post("/password")
def password(x:PasswordChange,request:Request,db:Session=Depends(get_db)):
 u=current_user(request,db);csrf_guard(request,db)
 try:ph.verify(u.password_hash,x.current_password)
 except VerifyMismatchError:raise HTTPException(401)
 if len(x.new_password)<12:raise HTTPException(400)
 u.password_hash=ph.hash(x.new_password);db.execute(delete(SessionToken).where(SessionToken.user_id==u.id));db.add(Audit(action="password.change",object_type="auth",object_id=u.id));db.commit();return {"ok":True}
@r.post("/logout")
def logout(request:Request,response:Response,db:Session=Depends(get_db)):
 tok=request.cookies.get(COOKIE)
 if tok:db.execute(delete(SessionToken).where(SessionToken.token_hash==h(tok)));db.commit()
 response.delete_cookie(COOKIE,path="/");return {"ok":True}

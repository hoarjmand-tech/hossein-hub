import os,json,hmac,hashlib,time
from pathlib import Path
from urllib.parse import parse_qsl
from fastapi import APIRouter,HTTPException,Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .core import get_db,ARCHIVE_ROOT
from .models import Document,Reminder
r=APIRouter(prefix="/api/telegram")
def secret(p):
 try:return Path(p).read_text().strip()
 except:return ""
TOKEN=secret(os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token"))
ADMIN_ID=secret(os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id"))
class Init(BaseModel):init_data:str
def validate(raw):
 d=dict(parse_qsl(raw,keep_blank_values=True));got=d.pop("hash",None)
 if not got:raise HTTPException(401,"Telegram signature missing")
 check="\n".join(f"{k}={d[k]}" for k in sorted(d))
 key=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
 calc=hmac.new(key,check.encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(calc,got):raise HTTPException(401,"Invalid Telegram signature")
 try:
  if abs(time.time()-int(d.get("auth_date","0")))>900:raise HTTPException(401,"Telegram session expired")
  user=json.loads(d.get("user","{}"))
 except (ValueError,json.JSONDecodeError):raise HTTPException(401)
 if not ADMIN_ID or str(user.get("id",""))!=ADMIN_ID:raise HTTPException(403,"Telegram account is not authorized")
 return user
@r.post("/login")
def login(x:Init):
 if not TOKEN:raise HTTPException(503,"Telegram not configured")
 u=validate(x.init_data);return {"ok":True,"user":{"id":u.get("id"),"first_name":u.get("first_name"),"username":u.get("username")}}
@r.post("/dashboard")
def dashboard(x:Init,db:Session=__import__("fastapi").Depends(get_db)):
 validate(x.init_data)
 return {"documents":db.scalar(select(func.count()).select_from(Document).where(Document.deleted==False)),"reminders":db.scalar(select(func.count()).select_from(Reminder).where(Reminder.done==False))}
@r.post("/documents")
def documents(x:Init,db:Session=__import__("fastapi").Depends(get_db)):
 validate(x.init_data)
 return [{"id":d.id,"title":d.title,"category":d.category,"expiry_date":d.expiry_date} for d in db.scalars(select(Document).where(Document.deleted==False).order_by(Document.created_at.desc()).limit(30))]

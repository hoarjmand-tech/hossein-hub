import os,shutil,platform
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter,Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,csrf_guard
r=APIRouter(prefix="/api/system",dependencies=[Depends(current_user)])
BACKUPS=Path(os.getenv("BACKUPS_ROOT","/backups"))
@r.get("/status")
def status(db:Session=Depends(get_db)):
 db.execute(text("select 1"))
 total,used,free=shutil.disk_usage("/")
 return {"app":"Hossein Hub","version":"2.0.0","database":"ok","hostname":platform.node(),"python":platform.python_version(),"disk":{"total":total,"used":used,"free":free},"time":datetime.utcnow().isoformat()+"Z"}
@r.get("/backups")
def backups():
 out=[]
 if BACKUPS.exists():
  for p in sorted((x for x in BACKUPS.iterdir() if x.is_dir()),reverse=True)[:50]:
   files=list(p.glob("*"));out.append({"name":p.name,"files":[x.name for x in files],"bytes":sum(x.stat().st_size for x in files if x.is_file()),"encrypted":any(x.suffix==".enc" for x in files)})
 return out

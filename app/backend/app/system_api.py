import os,shutil,platform,hashlib
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

@r.get("/backups/{name}/verify")
def verify_backup(name:str):
 p=(BACKUPS/name).resolve()
 if BACKUPS.resolve() not in p.parents or not p.is_dir():return {"ok":False,"error":"Backup not found"}
 sums=p/"SHA256SUMS"
 if not sums.exists():return {"ok":False,"error":"Missing SHA256SUMS"}
 results=[];all_ok=True
 for line in sums.read_text().splitlines():
  parts=line.strip().split(None,1)
  if len(parts)!=2:continue
  expected,fn=parts[0],parts[1].lstrip("*")
  f=p/fn
  if not f.exists():
   results.append({"file":fn,"ok":False,"error":"missing"});all_ok=False;continue
  h=hashlib.sha256()
  with f.open("rb") as z:
   for b in iter(lambda:z.read(1048576),b""):h.update(b)
  got=h.hexdigest();ok=got==expected;all_ok=all_ok and ok
  results.append({"file":fn,"ok":ok,"expected":expected,"actual":got})
 return {"ok":all_ok,"backup":name,"files":results}

import time,socket,urllib.request
from datetime import datetime
from sqlalchemy import select
from .core import SessionLocal
from .models import ManagedAsset,CheckResult,SystemAlert
def probe(a):
 t=time.monotonic()
 try:
  if a.protocol in ("http","https"):
   url=f"{a.protocol}://{a.address}"+(f":{a.port}" if a.port else "")+"/"
   with urllib.request.urlopen(url,timeout=5) as z:z.read(1)
  else:
   with socket.create_connection((a.address,a.port or 443),timeout=5):pass
  return "up",int((time.monotonic()-t)*1000),"reachable"
 except Exception as e:return "down",None,str(e)[:300]
while True:
 try:
  with SessionLocal() as db:
   for a in db.scalars(select(ManagedAsset).where(ManagedAsset.enabled==True)):
    old=a.last_status;st,lat,msg=probe(a);a.last_status=st;a.last_latency_ms=lat
    if st=="up":a.last_seen=datetime.utcnow()
    db.add(CheckResult(asset_id=a.id,status=st,latency_ms=lat,message=msg))
    if old=="up" and st=="down":db.add(SystemAlert(asset_id=a.id,severity="critical",title=f"{a.name} در دسترس نیست",body=msg))
    if old=="down" and st=="up":db.add(SystemAlert(asset_id=a.id,severity="info",title=f"{a.name} دوباره در دسترس است",body=f"Latency: {lat} ms"))
   db.commit()
 except Exception as e:print("monitor:",e,flush=True)
 time.sleep(60)

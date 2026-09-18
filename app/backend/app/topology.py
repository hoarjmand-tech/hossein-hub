import os,json,re
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user,csrf_guard
from .models import NetworkNeighborSnapshot,Audit

r=APIRouter(prefix="/api/topology",dependencies=[Depends(current_user)])
ROOT=Path(os.getenv("NETOPS_SECRETS_ROOT","/run/netops-secrets"));INV=ROOT/"devices.json"

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

def inv():
 try:
  x=json.loads(INV.read_text());return x if isinstance(x,list) else []
 except:return []

def secret(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

def connect(d):
 from netmiko import ConnectHandler
 kw={"device_type":d.get("device_type") or "cisco_ios","host":d["host"],"port":int(d.get("port",22)),
 "username":secret(d.get("username_file","")) or d.get("username",""),"password":secret(d.get("password_file","")),
 "secret":secret(d.get("enable_secret_file","")),"fast_cli":False,"conn_timeout":10,"auth_timeout":12,"banner_timeout":12}
 c=ConnectHandler(**kw)
 if kw["secret"]:
  try:c.enable()
  except:pass
 return c

def commands(dtype):
 if "mikrotik" in dtype:return ["/ip neighbor print detail without-paging"]
 if "juniper" in dtype:return ["show lldp neighbors detail"]
 if "fortinet" in dtype:return ["diagnose lldprx neighbor summary"]
 return ["show lldp neighbors detail","show cdp neighbors detail"]

def parse(raw,proto):
 blocks=re.split(r"\n\s*\n",raw)
 out=[]
 for b in blocks:
  if not b.strip():continue
  name=None;ip=None;li=None;ri=None;platform=None
  pats=[
   ("name",[r"(?:System Name|Device ID|identity)\s*[:=]\s*([^\n,]+)",r"neighbor\s+([^\s]+)"]),
   ("ip",[r"(?:Management Address|IP address|address)\s*[:=]\s*([0-9a-fA-F:.]+)"]),
   ("li",[r"(?:Local (?:Port|Interface|Intf)|interface)\s*[:=]\s*([^\n,]+)"]),
   ("ri",[r"(?:Port id|Port ID|Port Identifier|port)\s*[:=]\s*([^\n,]+)"]),
   ("platform",[r"(?:Platform|System Description|board-name)\s*[:=]\s*([^\n]+)"])
  ]
  vals={}
  for key,arr in pats:
   for p in arr:
    m=re.search(p,b,re.I)
    if m:vals[key]=m.group(1).strip();break
  name=vals.get("name");ip=vals.get("ip");li=vals.get("li");ri=vals.get("ri");platform=vals.get("platform")
  if name or ip or li or ri:out.append({"neighbor_name":name,"neighbor_ip":ip,"local_interface":li,"neighbor_interface":ri,"platform":platform,"protocol":proto,"raw_text":b[:4000]})
 return out

@r.post("/collect",dependencies=[Depends(csrf_guard)])
def collect(db:Session=Depends(get_db),u=Depends(admin)):
 devices=inv();results=[];stamp=datetime.utcnow()
 for d in devices:
  if not d.get("enabled",True) or not d.get("username_file"):continue
  c=None;found=[];errors=[]
  try:
   c=connect(d)
   for cmd in commands(d.get("device_type") or ""):
    try:
     raw=c.send_command(cmd,read_timeout=90)
     parsed=parse(raw,"lldp" if "lldp" in cmd.lower() or "neighbor" in cmd.lower() else "cdp")
     if parsed:found.extend(parsed);break
    except Exception as e:errors.append(str(e)[:200])
   db.execute(delete(NetworkNeighborSnapshot).where(NetworkNeighborSnapshot.local_device_id==str(d.get("id"))))
   for n in found:
    db.add(NetworkNeighborSnapshot(local_device_id=str(d.get("id")),local_device_name=d.get("name") or d.get("host"),
      local_interface=n.get("local_interface"),neighbor_name=n.get("neighbor_name"),neighbor_ip=n.get("neighbor_ip"),
      neighbor_interface=n.get("neighbor_interface"),platform=n.get("platform"),protocol=n.get("protocol"),raw_text=n.get("raw_text"),collected_at=stamp))
   results.append({"device":d.get("name") or d.get("host"),"ok":True,"neighbors":len(found),"errors":errors})
  except Exception as e:results.append({"device":d.get("name") or d.get("host"),"ok":False,"error":str(e)[:500]})
  finally:
   try:
    if c:c.disconnect()
   except:pass
 db.add(Audit(action="topology.collect",object_type="network",detail=f"devices={len(results)} by {u.username}"));db.commit()
 return {"devices":len(results),"neighbors":sum(x.get("neighbors",0) for x in results),"results":results}

@r.get("/graph")
def graph(db:Session=Depends(get_db),u=Depends(admin)):
 devices=inv()
 nodes=[{"id":str(d.get("id")),"label":d.get("name") or d.get("host"),"host":d.get("host"),"type":d.get("device_type"),"site":d.get("site"),"role":d.get("role"),"managed":True} for d in devices]
 node_ids={x["id"] for x in nodes};edges=[]
 rows=list(db.scalars(select(NetworkNeighborSnapshot).order_by(NetworkNeighborSnapshot.collected_at.desc())))
 for x in rows:
  nid="neighbor:"+str(x.neighbor_ip or x.neighbor_name or x.id)
  target=next((d for d in devices if (x.neighbor_ip and d.get("host")==x.neighbor_ip) or (x.neighbor_name and str(d.get("name","")).lower()==str(x.neighbor_name).lower())),None)
  tid=str(target.get("id")) if target else nid
  if tid not in node_ids:
   nodes.append({"id":tid,"label":x.neighbor_name or x.neighbor_ip or "Unknown","host":x.neighbor_ip,"type":x.platform,"managed":False});node_ids.add(tid)
  edges.append({"source":x.local_device_id,"target":tid,"local_interface":x.local_interface,"neighbor_interface":x.neighbor_interface,"protocol":x.protocol})
 return {"nodes":nodes,"edges":edges,"collected":len(rows)}

import ipaddress,socket,urllib.request,ssl,concurrent.futures,os
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from .auth import current_user,csrf_guard

r=APIRouter(prefix="/api/netops-discovery",dependencies=[Depends(current_user)])
CIDRS=[x.strip() for x in os.getenv("NETOPS_DISCOVERY_CIDRS","192.168.1.0/24,192.168.22.0/24").split(",") if x.strip()]
PORTS=[22,23,80,443,8291,8728,8729,9042]

def admin(u=Depends(current_user)):
 if not u.is_admin:raise HTTPException(403,"Admin required")
 return u

def tcp(ip,port,timeout=.35):
 try:
  with socket.create_connection((ip,port),timeout=timeout) as s:
   banner=""
   if port in (22,23):
    try:s.settimeout(.25);banner=s.recv(160).decode(errors="ignore").strip()
    except:pass
   return True,banner
 except:return False,""

def http_hint(ip,port):
 scheme="https" if port in (443,9042) else "http"
 try:
  req=urllib.request.Request(f"{scheme}://{ip}:{port}/",method="HEAD",headers={"User-Agent":"HosseinHub-Discovery/1"})
  ctx=ssl._create_unverified_context() if scheme=="https" else None
  with urllib.request.urlopen(req,timeout=.7,context=ctx) as x:
   return " ".join(filter(None,[x.headers.get("Server",""),x.headers.get("WWW-Authenticate","")]))[:220]
 except Exception as e:
  return str(e)[:160]

def infer(ports,banners,hints):
 text=(" ".join(banners.values())+" "+" ".join(hints.values())).lower()
 if 9042 in ports or "fortigate" in text or "fortinet" in text:return "fortinet","firewall"
 if 8291 in ports or 8728 in ports or 8729 in ports or "mikrotik" in text:return "mikrotik_routeros","router"
 if "nx-os" in text or "nexus" in text:return "cisco_nxos","switch"
 if "cisco" in text:return "cisco_ios","switch"
 if "junos" in text or "juniper" in text:return "juniper_junos","switch"
 if "arista" in text or "eos" in text:return "arista_eos","switch"
 if 22 in ports:return "linux","unknown"
 return "unknown","unknown"

def scan_host(ip):
 opened=[];banners={};hints={}
 for p in PORTS:
  ok,b=tcp(ip,p)
  if ok:
   opened.append(p)
   if b:banners[str(p)]=b
 if not opened:return None
 for p in opened:
  if p in (80,443,9042):hints[str(p)]=http_hint(ip,p)
 try:name=socket.gethostbyaddr(ip)[0]
 except:name=ip
 dtype,role=infer(opened,banners,hints)
 return {"host":ip,"name":name,"ports":opened,"device_type":dtype,"role":role,"banners":banners,"hints":hints}

@r.post("/scan",dependencies=[Depends(csrf_guard)])
def scan(u=Depends(admin)):
 hosts=[]
 for raw in CIDRS:
  try:
   net=ipaddress.ip_network(raw,strict=False)
   if not net.is_private:continue
   hosts.extend(str(x) for x in net.hosts())
  except:continue
 out=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=96) as ex:
  for x in ex.map(scan_host,hosts):
   if x:out.append(x)
 out.sort(key=lambda z:tuple(int(p) for p in z["host"].split(".")) if "." in z["host"] else (999,))
 return {"cidrs":CIDRS,"count":len(out),"devices":out}

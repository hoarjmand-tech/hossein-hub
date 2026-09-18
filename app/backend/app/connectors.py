import os,json,ssl,urllib.request,urllib.parse,base64
from pathlib import Path
from fastapi import APIRouter,Depends
from .auth import current_user,csrf_guard
r=APIRouter(prefix="/api/connectors",dependencies=[Depends(current_user),Depends(csrf_guard)])
ROOT=Path(os.getenv("CONNECTOR_SECRETS_ROOT","/run/connector-secrets"))

def sec(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""

def cfg(name):
 try:return json.loads((ROOT/name).read_text())
 except:return {}

def http_json(url,headers=None,method="GET",body=None,verify=False,timeout=12,form=False):
 data=None;h=dict(headers or {})
 if body is not None:
  if form:
   data=urllib.parse.urlencode(body).encode();h.setdefault("Content-Type","application/x-www-form-urlencoded")
  else:
   data=json.dumps(body).encode();h.setdefault("Content-Type","application/json")
 req=urllib.request.Request(url,data=data,headers=h,method=method)
 ctx=None if verify else ssl._create_unverified_context()
 with urllib.request.urlopen(req,timeout=timeout,context=ctx) as resp:
  raw=resp.read()
  try:return json.loads(raw)
  except:return {"status":resp.status,"body":raw.decode(errors="ignore")[:2000]}

# ---------- FortiGate ----------
def fg_base():
 c=cfg("fortigate.json");host=c.get("host")
 if not host:return c,None
 scheme=c.get("scheme","https");port=int(c.get("port",9042))
 return c,f"{scheme}://{host}:{port}"

def fg_get(path):
 c,b=fg_base();token=sec("fortigate_token")
 if not b or not token:return {"configured":False}
 try:
  x=http_json(b+path,{"Authorization":f"Bearer {token}"},verify=c.get("verify_tls",False))
  return {"configured":True,"ok":True,"data":x}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:500]}

def fortigate_summary():return fg_get("/api/v2/monitor/system/status")
def fortigate_interfaces():return fg_get("/api/v2/monitor/system/interface")
def fortigate_sessions():return fg_get("/api/v2/monitor/firewall/session?count=100")

# ---------- VMware ESXi / vCenter ----------
def vmware_inventory():
 c=cfg("esxi.json");host=c.get("host");user=sec("esxi_user");password=sec("esxi_password")
 if not host or not user or not password:return {"configured":False}
 try:
  from pyVim.connect import SmartConnect,SmartConnectNoSSL,Disconnect
  from pyVmomi import vim
  connect=SmartConnect if c.get("verify_tls",False) else SmartConnectNoSSL
  si=connect(host=host,user=user,pwd=password,port=int(c.get("port",443)))
  content=si.RetrieveContent()
  vms=[];hosts=[];datastores=[]
  view=content.viewManager.CreateContainerView(content.rootFolder,[vim.VirtualMachine],True)
  for x in view.view:
   cfgx=x.config
   vms.append({"name":x.name,"power":str(x.runtime.powerState),"cpu":getattr(getattr(cfgx,"hardware",None),"numCPU",None),"memory_mb":getattr(getattr(cfgx,"hardware",None),"memoryMB",None),"guest":getattr(cfgx,"guestFullName",None)})
  view.Destroy()
  view=content.viewManager.CreateContainerView(content.rootFolder,[vim.HostSystem],True)
  for x in view.view:
   hw=x.hardware
   hosts.append({"name":x.name,"connection":str(x.runtime.connectionState),"maintenance":bool(x.runtime.inMaintenanceMode),"cpu_threads":getattr(getattr(hw,"cpuInfo",None),"numCpuThreads",None),"memory_bytes":getattr(hw,"memorySize",None)})
  view.Destroy()
  view=content.viewManager.CreateContainerView(content.rootFolder,[vim.Datastore],True)
  for x in view.view:
   s=x.summary
   datastores.append({"name":x.name,"accessible":bool(s.accessible),"capacity":int(s.capacity or 0),"free":int(s.freeSpace or 0),"type":s.type})
  view.Destroy()
  Disconnect(si)
  return {"configured":True,"ok":True,"data":{"hosts":hosts,"vms":vms,"datastores":datastores}}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:500]}

# ---------- Veeam Backup & Replication ----------
def veeam_base():
 c=cfg("veeam.json");host=c.get("host")
 if not host:return c,None
 return c,f"{c.get('scheme','https')}://{host}:{int(c.get('port',9419))}/api/v1"

def veeam_token():
 c,b=veeam_base()
 if not b:return None
 static=sec("veeam_token")
 if static:return static
 user=sec("veeam_user");password=sec("veeam_password")
 if not user or not password:return None
 try:
  x=http_json(b+"/token",method="POST",body={"grant_type":"password","username":user,"password":password},verify=c.get("verify_tls",False),form=True)
  return x.get("access_token")
 except:return None

def veeam_get(path):
 c,b=veeam_base();token=veeam_token()
 if not b or not token:return {"configured":bool(b),"ok":False if b else None,"error":"Credentials not configured" if b else None}
 try:
  h={"Authorization":f"Bearer {token}","x-api-version":c.get("api_version","1.2-rev1")}
  return {"configured":True,"ok":True,"data":http_json(b+path,h,verify=c.get("verify_tls",False))}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:500]}

def veeam_summary():return veeam_get("/serverInfo")
def veeam_jobs():return veeam_get("/jobs?limit=100")
def veeam_sessions():return veeam_get("/sessions?limit=100")

@r.get("")
def all_connectors():
 return {"fortigate":fortigate_summary(),"esxi":vmware_inventory(),"veeam":veeam_summary()}

@r.get("/fortigate/summary")
def fg_summary():return fortigate_summary()

@r.get("/fortigate/interfaces")
def fg_interfaces():return fortigate_interfaces()

@r.get("/fortigate/sessions")
def fg_sessions():return fortigate_sessions()

@r.get("/esxi/inventory")
def esxi_inventory():return vmware_inventory()

@r.get("/veeam/summary")
def v_summary():return veeam_summary()

@r.get("/veeam/jobs")
def v_jobs():return veeam_jobs()

@r.get("/veeam/sessions")
def v_sessions():return veeam_sessions()

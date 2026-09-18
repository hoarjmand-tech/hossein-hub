import os,json,ssl,urllib.request,urllib.error
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from .auth import current_user,csrf_guard
r=APIRouter(prefix="/api/connectors",dependencies=[Depends(current_user),Depends(csrf_guard)])
ROOT=Path(os.getenv("CONNECTOR_SECRETS_ROOT","/run/connector-secrets"))
def sec(name):
 try:return (ROOT/name).read_text().strip()
 except:return ""
def jsec(name):
 try:return json.loads((ROOT/name).read_text())
 except:return {}
def request_json(url,headers=None,method="GET",body=None,verify=True,timeout=8):
 data=None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(url,data=data,headers=headers or {},method=method)
 ctx=None
 if not verify:
  ctx=ssl._create_unverified_context()
 with urllib.request.urlopen(req,timeout=timeout,context=ctx) as resp:
  raw=resp.read()
  try:return json.loads(raw)
  except:return {"status":resp.status,"body":raw[:500].decode(errors="ignore")}
def fortigate_status():
 cfg=jsec("fortigate.json")
 if not cfg:return {"configured":False}
 host=cfg.get("host");token=sec("fortigate_token")
 if not host or not token:return {"configured":False}
 try:
  x=request_json(f"https://{host}/api/v2/monitor/system/status",headers={"Authorization":f"Bearer {token}"},verify=cfg.get("verify_tls",False))
  return {"configured":True,"ok":True,"data":x}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:300]}
def esxi_status():
 cfg=jsec("esxi.json")
 if not cfg:return {"configured":False}
 host=cfg.get("host");user=sec("esxi_user");password=sec("esxi_password")
 if not host or not user or not password:return {"configured":False}
 try:
  import base64
  h={"Authorization":"Basic "+base64.b64encode(f"{user}:{password}".encode()).decode()}
  x=request_json(f"https://{host}/rest/vcenter/system-config/about",headers=h,verify=cfg.get("verify_tls",False))
  return {"configured":True,"ok":True,"data":x}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:300]}
def veeam_status():
 cfg=jsec("veeam.json")
 if not cfg:return {"configured":False}
 host=cfg.get("host");token=sec("veeam_token")
 if not host or not token:return {"configured":False}
 try:
  x=request_json(f"https://{host}:9419/api/v1/serverInfo",headers={"Authorization":f"Bearer {token}","x-api-version":"1.2-rev1"},verify=cfg.get("verify_tls",False))
  return {"configured":True,"ok":True,"data":x}
 except Exception as e:return {"configured":True,"ok":False,"error":str(e)[:300]}
@r.get("")
def all_connectors():
 return {"fortigate":fortigate_status(),"esxi":esxi_status(),"veeam":veeam_status()}
@r.get("/fortigate")
def fortigate():return fortigate_status()
@r.get("/esxi")
def esxi():return esxi_status()
@r.get("/veeam")
def veeam():return veeam_status()

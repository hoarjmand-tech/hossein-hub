from collections import Counter,defaultdict
from fastapi import APIRouter,Depends
from .auth import current_user,csrf_guard
from .connectors import fortigate_sessions,fortigate_interfaces,vmware_inventory,veeam_jobs,veeam_sessions
r=APIRouter(prefix="/api/infra-analytics",dependencies=[Depends(current_user),Depends(csrf_guard)])

def rows(x):
 d=(x or {}).get("data")
 if isinstance(d,list):return d
 if isinstance(d,dict):
  for k in ("results","data","items","sessions","interfaces","jobs"):
   v=d.get(k)
   if isinstance(v,list):return v
 return []

@r.get("/fortigate/top")
def fg_top():
 s=fortigate_sessions(); rr=rows(s)
 src=Counter();dst=Counter();apps=Counter();users=Counter();bytes_by_src=defaultdict(int)
 for x in rr:
  sip=str(x.get("srcip") or x.get("src") or x.get("source_ip") or "")
  dip=str(x.get("dstip") or x.get("dst") or x.get("destination_ip") or "")
  app=str(x.get("app") or x.get("app_name") or x.get("application") or "")
  user=str(x.get("user") or x.get("username") or "")
  b=int(x.get("sentbyte") or 0)+int(x.get("rcvdbyte") or 0)
  if sip:src[sip]+=1;bytes_by_src[sip]+=b
  if dip:dst[dip]+=1
  if app:apps[app]+=1
  if user:users[user]+=1
 return {"ok":s.get("ok"),"configured":s.get("configured"),"total_sessions":len(rr),
 "top_sources":[{"name":k,"sessions":v,"bytes":bytes_by_src[k]} for k,v in src.most_common(15)],
 "top_destinations":[{"name":k,"sessions":v} for k,v in dst.most_common(15)],
 "top_apps":[{"name":k,"sessions":v} for k,v in apps.most_common(15)],
 "top_users":[{"name":k,"sessions":v} for k,v in users.most_common(15)]}

@r.get("/fortigate/interfaces")
def fg_interfaces():
 x=fortigate_interfaces();return x

@r.get("/vmware/summary")
def vmware_summary():
 x=vmware_inventory()
 if not x.get("ok"):return x
 d=x.get("data") or {};vms=d.get("vms") or [];hosts=d.get("hosts") or [];ds=d.get("datastores") or []
 powered=sum(1 for v in vms if "poweredOn" in str(v.get("power")))
 down=sum(1 for h in hosts if "connected" not in str(h.get("connection")))
 return {"configured":True,"ok":True,"hosts":len(hosts),"hosts_problem":down,"vms":len(vms),"vms_on":powered,
 "datastores":len(ds),"vm_items":vms,"host_items":hosts,"datastore_items":ds}

@r.get("/veeam/summary")
def veeam_summary():
 j=veeam_jobs();s=veeam_sessions()
 jr=rows(j);sr=rows(s)
 failed=[];success=0;running=0
 for x in sr:
  st=str(x.get("state") or x.get("result") or x.get("status") or "").lower()
  if "fail" in st or "error" in st:failed.append(x)
  elif "success" in st:success+=1
  elif "run" in st or "working" in st:running+=1
 return {"configured":j.get("configured") or s.get("configured"),"ok":bool(j.get("ok") or s.get("ok")),
 "jobs":len(jr),"sessions":len(sr),"successful":success,"running":running,"failed":len(failed),"failed_items":failed[:20],
 "job_items":jr[:100],"session_items":sr[:100]}

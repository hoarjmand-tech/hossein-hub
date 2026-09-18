from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user,csrf_guard
from .core import get_db
from .models import ManagedAsset,SystemAlert,Document,ComplianceResult,NetworkChangeJob,NetworkNeighborSnapshot,DeviceConfigSnapshot
from .connectors import fortigate_summary,vmware_inventory,veeam_summary
r=APIRouter(prefix="/api/ops-assistant",dependencies=[Depends(current_user),Depends(csrf_guard)])
class Ask(BaseModel):query:str=Field(min_length=2,max_length=500)
@r.post("/ask")
def ask(x:Ask,db:Session=Depends(get_db)):
 q=x.query.strip().lower()
 if any(k in q for k in ("fortigate","forti","فورتی")):return {"type":"connector","connector":"fortigate","result":fortigate_summary()}
 if any(k in q for k in ("esxi","vmware","وی ام","ای اس ایکس")):return {"type":"connector","connector":"esxi","result":vmware_inventory()}
 if any(k in q for k in ("veeam","backup","بکاپ","بک آپ")):return {"type":"connector","connector":"veeam","result":veeam_summary()}
 if any(k in q for k in ("down","قطع","خاموش","دردسترس")):
  a=list(db.scalars(select(ManagedAsset).where(ManagedAsset.last_status=="down")))
  return {"type":"assets","items":[{"name":z.name,"address":z.address,"port":z.port,"status":z.last_status} for z in a]}
 if any(k in q for k in ("alert","هشدار")):
  a=list(db.scalars(select(SystemAlert).where(SystemAlert.acknowledged==False).order_by(SystemAlert.created_at.desc()).limit(20)))
  return {"type":"alerts","items":[{"title":z.title,"severity":z.severity,"created_at":z.created_at} for z in a]}
 if any(k in q for k in ("compliance","policy","کامپلاینس","پالیسی")):
  a=list(db.scalars(select(ComplianceResult).where(ComplianceResult.status=="fail").order_by(ComplianceResult.checked_at.desc()).limit(30)))
  return {"type":"compliance","items":[{"device":z.device_name,"policy":z.policy_name,"detail":z.detail,"checked_at":z.checked_at} for z in a]}
 if any(k in q for k in ("topology","lldp","cdp","توپولوژی","همسایه")):
  a=list(db.scalars(select(NetworkNeighborSnapshot).order_by(NetworkNeighborSnapshot.collected_at.desc()).limit(100)))
  return {"type":"topology","items":[{"local":z.local_device_name,"local_interface":z.local_interface,"neighbor":z.neighbor_name,"neighbor_ip":z.neighbor_ip,"neighbor_interface":z.neighbor_interface,"platform":z.platform} for z in a]}
 if any(k in q for k in ("netops","change","تغییر کانفیگ","جاب")):
  a=list(db.scalars(select(NetworkChangeJob).order_by(NetworkChangeJob.created_at.desc()).limit(20)))
  return {"type":"netops_jobs","items":[{"device":z.device_name,"status":z.status,"requested_by":z.requested_by,"created_at":z.created_at,"error":z.error} for z in a]}
 if any(k in q for k in ("drift","config","کانفیگ","snapshot")):
  a=list(db.scalars(select(DeviceConfigSnapshot).order_by(DeviceConfigSnapshot.created_at.desc()).limit(20)))
  return {"type":"config_snapshots","items":[{"device":z.device_name,"source":z.source,"created_at":z.created_at,"sha256":z.sha256} for z in a]}
 if any(k in q for k in ("document","سند","مدرک")):
  a=list(db.scalars(select(Document).where(Document.deleted==False).order_by(Document.created_at.desc()).limit(20)))
  return {"type":"documents","items":[{"title":z.title,"category":z.category,"expiry_date":z.expiry_date} for z in a]}
 return {"type":"help","message":"می‌توانم FortiGate، ESXi، Veeam، تجهیزات Down، هشدارها، Compliance، Topology، NetOps Jobs، Config Snapshots و اسناد را بررسی کنم."}

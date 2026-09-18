from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user,csrf_guard
from .core import get_db
from .models import ManagedAsset,SystemAlert,Document
from .connectors import fortigate_status,esxi_status,veeam_status
r=APIRouter(prefix="/api/ops-assistant",dependencies=[Depends(current_user),Depends(csrf_guard)])
class Ask(BaseModel):query:str=Field(min_length=2,max_length=500)
@r.post("/ask")
def ask(x:Ask,db:Session=Depends(get_db)):
 q=x.query.strip().lower()
 if any(k in q for k in ("fortigate","forti","فورتی")):return {"type":"connector","connector":"fortigate","result":fortigate_status()}
 if any(k in q for k in ("esxi","vmware","وی ام","ای اس ایکس")):return {"type":"connector","connector":"esxi","result":esxi_status()}
 if any(k in q for k in ("veeam","backup","بکاپ","بک آپ")):return {"type":"connector","connector":"veeam","result":veeam_status()}
 if any(k in q for k in ("down","قطع","خاموش","دردسترس")):
  a=list(db.scalars(select(ManagedAsset).where(ManagedAsset.last_status=="down")))
  return {"type":"assets","items":[{"name":z.name,"address":z.address,"port":z.port,"status":z.last_status} for z in a]}
 if any(k in q for k in ("alert","هشدار")):
  a=list(db.scalars(select(SystemAlert).where(SystemAlert.acknowledged==False).order_by(SystemAlert.created_at.desc()).limit(20)))
  return {"type":"alerts","items":[{"title":z.title,"severity":z.severity,"created_at":z.created_at} for z in a]}
 if any(k in q for k in ("document","سند","مدرک")):
  a=list(db.scalars(select(Document).where(Document.deleted==False).order_by(Document.created_at.desc()).limit(20)))
  return {"type":"documents","items":[{"title":z.title,"category":z.category,"expiry_date":z.expiry_date} for z in a]}
 return {"type":"help","message":"می‌توانم وضعیت FortiGate، ESXi، Veeam، تجهیزات Down، هشدارها و آخرین اسناد را بررسی کنم."}

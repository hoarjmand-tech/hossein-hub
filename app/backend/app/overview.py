from fastapi import APIRouter,Depends
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .core import get_db
from .auth import current_user
from .models import ManagedAsset,SystemAlert,Document,Reminder,Notification,ShareLink
r=APIRouter(prefix="/api/overview",dependencies=[Depends(current_user)])
@r.get("")
def overview(db:Session=Depends(get_db)):
 return {
  "documents":db.scalar(select(func.count()).select_from(Document).where(Document.deleted==False)) or 0,
  "reminders":db.scalar(select(func.count()).select_from(Reminder).where(Reminder.done==False)) or 0,
  "notifications":db.scalar(select(func.count()).select_from(Notification).where(Notification.read==False)) or 0,
  "assets":db.scalar(select(func.count()).select_from(ManagedAsset)) or 0,
  "assets_down":db.scalar(select(func.count()).select_from(ManagedAsset).where(ManagedAsset.last_status=="down")) or 0,
  "alerts_open":db.scalar(select(func.count()).select_from(SystemAlert).where(SystemAlert.acknowledged==False)) or 0,
  "active_shares":db.scalar(select(func.count()).select_from(ShareLink).where(ShareLink.active==True)) or 0
 }

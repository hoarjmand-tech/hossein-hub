import time
from datetime import datetime,timedelta
from sqlalchemy import delete
from .core import SessionLocal
from .models import SessionToken,ShareLink,CheckResult,Audit,ConnectorSample
while True:
 try:
  with SessionLocal() as db:
   now=datetime.utcnow()
   db.execute(delete(SessionToken).where(SessionToken.expires_at<now))
   db.execute(delete(ShareLink).where(ShareLink.expires_at<now-timedelta(days=7)))
   db.execute(delete(CheckResult).where(CheckResult.checked_at<now-timedelta(days=90)))
   db.execute(delete(ConnectorSample).where(ConnectorSample.sampled_at<now-timedelta(days=30)))
   db.execute(delete(Audit).where(Audit.at<now-timedelta(days=365)))
   db.commit()
 except Exception as e:print("maintenance:",e,flush=True)
 time.sleep(21600)

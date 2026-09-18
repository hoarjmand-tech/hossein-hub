import os
from pathlib import Path
from fastapi import Header, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL=os.environ["DATABASE_URL"]
ARCHIVE_ROOT=Path(os.getenv("ARCHIVE_ROOT","/archive")).resolve()
MAX_UPLOAD=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
API_KEY=os.environ["HUB_API_KEY"]
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
SessionLocal=sessionmaker(engine,expire_on_commit=False)

def get_db():
    with SessionLocal() as db: yield db

def require_key(x_api_key:str=Header(...)):
    import hmac
    if not hmac.compare_digest(x_api_key,API_KEY): raise HTTPException(401,"Unauthorized")

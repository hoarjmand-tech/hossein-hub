import os
from pathlib import Path
from urllib.parse import quote_plus
from fastapi import Header,HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
def secret(path):
 try:return Path(path).read_text().strip()
 except Exception:return ""
DB_USER=os.getenv("POSTGRES_USER","hubadmin");DB_NAME=os.getenv("POSTGRES_DB","hossein_hub");DB_HOST=os.getenv("POSTGRES_HOST","postgres")
DB_PASS=secret(os.getenv("POSTGRES_PASSWORD_FILE","/run/secrets/postgres_password")) or os.getenv("POSTGRES_PASSWORD","")
DATABASE_URL=os.getenv("DATABASE_URL") or f"postgresql+psycopg://{quote_plus(DB_USER)}:{quote_plus(DB_PASS)}@{DB_HOST}:5432/{DB_NAME}"
ARCHIVE_ROOT=Path(os.getenv("ARCHIVE_ROOT","/archive")).resolve();MAX_UPLOAD=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
API_KEY=secret(os.getenv("HUB_API_KEY_FILE","/run/secrets/hub_api_key")) or os.getenv("HUB_API_KEY","")
if not API_KEY: raise RuntimeError("HUB API key is not configured")
engine=create_engine(DATABASE_URL,pool_pre_ping=True);SessionLocal=sessionmaker(engine,expire_on_commit=False)
def get_db():
 with SessionLocal() as db:yield db
def require_key(x_api_key:str=Header(...)):
 import hmac
 if not hmac.compare_digest(x_api_key,API_KEY):raise HTTPException(401,"Unauthorized")

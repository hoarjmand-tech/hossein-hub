from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text
from .core import engine
from .models import Base
from .archive import r as archive_router
from .auth import r as auth_router
from .extras import r as extras_router
from .manage import r as manage_router
from .telegram_app import r as telegram_router
from .it import r as it_router
from .assistant import r as assistant_router
Base.metadata.create_all(engine)
app=FastAPI(title="Hossein Hub",version="1.2.0")
app.include_router(auth_router)
app.include_router(archive_router)
app.include_router(extras_router)
app.include_router(manage_router)
app.include_router(telegram_router)
app.include_router(it_router)
app.include_router(assistant_router)
WEB=Path(__file__).parent/"web"
NO_CACHE={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"}
@app.get("/",include_in_schema=False)
def home(): return FileResponse(WEB/"home.html",headers=NO_CACHE)
@app.get("/it",include_in_schema=False)
def it_home(): return FileResponse(WEB/"it.html",headers=NO_CACHE)
@app.get("/telegram",include_in_schema=False)
def telegram_miniapp(): return FileResponse(WEB/"telegram.html",headers=NO_CACHE)
@app.get("/archive",include_in_schema=False)
def archive_home(): return FileResponse(WEB/"index.html",headers=NO_CACHE)
@app.get("/manifest.json",include_in_schema=False)
def manifest(): return FileResponse(WEB/"manifest.json",media_type="application/manifest+json",headers=NO_CACHE)
@app.get("/sw.js",include_in_schema=False)
def sw(): return FileResponse(WEB/"sw.js",media_type="application/javascript",headers=NO_CACHE)
@app.get("/health")
def health():
 with engine.connect() as c:c.execute(text("select 1"))
 return {"status":"ok","database":"ok","module":"archive","version":"1.2.0"}

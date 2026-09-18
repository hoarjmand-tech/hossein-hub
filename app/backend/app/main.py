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
from .system_api import r as system_router
from .overview import r as overview_router
from .bulk_import import r as bulk_router
from .it_history import r as it_history_router
from .admin import r as admin_router
from .reports import r as reports_router
from .connectors import r as connectors_router
from .ops_assistant import r as ops_assistant_router
from .infra_analytics import r as infra_analytics_router
Base.metadata.create_all(engine)
app=FastAPI(title="Hossein Hub",version="2.0.0")
app.include_router(auth_router)
app.include_router(archive_router)
app.include_router(extras_router)
app.include_router(manage_router)
app.include_router(telegram_router)
app.include_router(it_router)
app.include_router(assistant_router)
app.include_router(system_router)
app.include_router(overview_router)
app.include_router(bulk_router)
app.include_router(it_history_router)
app.include_router(admin_router)
app.include_router(reports_router)
app.include_router(connectors_router)
app.include_router(ops_assistant_router)
app.include_router(infra_analytics_router)
WEB=Path(__file__).parent/"web"
NO_CACHE={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"}
@app.get("/",include_in_schema=False)
def home(): return FileResponse(WEB/"home.html",headers=NO_CACHE)
@app.get("/fortigate",include_in_schema=False)
def fortigate_home(): return FileResponse(WEB/"fortigate.html",headers=NO_CACHE)
@app.get("/esxi",include_in_schema=False)
def esxi_home(): return FileResponse(WEB/"esxi.html",headers=NO_CACHE)
@app.get("/veeam",include_in_schema=False)
def veeam_home(): return FileResponse(WEB/"veeam.html",headers=NO_CACHE)
@app.get("/connectors",include_in_schema=False)
def connectors_home(): return FileResponse(WEB/"connectors.html",headers=NO_CACHE)
@app.get("/ops",include_in_schema=False)
def ops_home(): return FileResponse(WEB/"ops.html",headers=NO_CACHE)
@app.get("/imports",include_in_schema=False)
def imports_home(): return FileResponse(WEB/"imports.html",headers=NO_CACHE)
@app.get("/admin",include_in_schema=False)
def admin_home(): return FileResponse(WEB/"admin.html",headers=NO_CACHE)
@app.get("/reports",include_in_schema=False)
def reports_home(): return FileResponse(WEB/"reports.html",headers=NO_CACHE)
@app.get("/assistant",include_in_schema=False)
def assistant_home(): return FileResponse(WEB/"assistant.html",headers=NO_CACHE)
@app.get("/notifications",include_in_schema=False)
def notifications_home(): return FileResponse(WEB/"notifications.html",headers=NO_CACHE)
@app.get("/backups",include_in_schema=False)
def backups_home(): return FileResponse(WEB/"backups.html",headers=NO_CACHE)
@app.get("/settings",include_in_schema=False)
def settings_home(): return FileResponse(WEB/"settings.html",headers=NO_CACHE)
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
 return {"status":"ok","database":"ok","module":"hub","version":"2.0.0"}

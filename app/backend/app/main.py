from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text
from .core import engine
from .models import Base
from .archive import r
Base.metadata.create_all(engine)
app=FastAPI(title="Hossein Hub",version="0.4.0")
app.include_router(r)
WEB=Path(__file__).parent/"web"
@app.get("/",include_in_schema=False)
def home(): return FileResponse(WEB/"index.html")
@app.get("/manifest.json",include_in_schema=False)
def manifest(): return FileResponse(WEB/"manifest.json",media_type="application/manifest+json")
@app.get("/sw.js",include_in_schema=False)
def sw(): return FileResponse(WEB/"sw.js",media_type="application/javascript")
@app.get("/health")
def health():
    with engine.connect() as c:c.execute(text("select 1"))
    return {"status":"ok","database":"ok","module":"archive","version":"0.4.0"}

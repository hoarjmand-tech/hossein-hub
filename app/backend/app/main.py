from fastapi import FastAPI
from sqlalchemy import text
from .core import engine
from .models import Base
from .archive import r
Base.metadata.create_all(engine)
app=FastAPI(title="Hossein Hub",version="0.3.0")
app.include_router(r)
@app.get("/health")
def health():
    with engine.connect() as c:c.execute(text("select 1"))
    return {"status":"ok","database":"ok","module":"archive","version":"0.3.0"}

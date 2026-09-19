import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

import magic
from fastapi import Body, Cookie, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pypdf import PdfReader

ROOT=Path(os.getenv("ARCHIVE_ROOT","/data"))
FILES=ROOT/"files"
TMP=ROOT/"tmp"
DB_PATH=ROOT/"archive.db"
WEB=Path(__file__).parent/"web"
MAX_UPLOAD=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true"
for p in (ROOT,FILES,TMP): p.mkdir(parents=True,exist_ok=True)

def read_secret(path,env_name):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return os.getenv(env_name,"").strip()

DRIVE_TOKEN=read_secret(os.getenv("DRIVE_PUSH_TOKEN_FILE","/run/secrets/drive_push_token"),"DRIVE_PUSH_TOKEN")
ALLOWED={"application/pdf","image/jpeg","image/png","image/webp","image/tiff"}
GENERIC_NAME=re.compile(r"^(scan|img|image|document|doc|photo|screenshot)[ _-]*[0-9 _.-]*$",re.I)

CATEGORY_RULES=[
    ("identity","گذرنامه",["passport","reisepass","گذرنامه","پاسپورت","islamic republic of iran"]),
    ("identity","کارت اقامت",["aufenthaltstitel","niederlassungsbewilligung","residence permit","aufenthaltskarte","کارت اقامت"]),
    ("identity","گواهینامه رانندگی",["führerschein","driving licence","driving license","گواهینامه رانندگی"]),
    ("legal","نامه MA35",["ma35","magistratsabteilung 35"]),
    ("legal","سند حقوقی",["gericht","court","bescheid","beschwerde","vollmacht","دادگاه","وکالت نامه","وکالتنامه"]),
    ("housing","قرارداد اجاره",["mietvertrag","hauptmietvertrag","rental agreement","lease agreement","قرارداد اجاره","اجاره نامه","اجاره‌نامه"]),
    ("insurance","بیمه ARAG",["arag","rechtsschutz"]),
    ("insurance","بیمه درمان",["ögk","österreichische gesundheitskasse","krankenversicherung","health insurance","بیمه درمان"]),
    ("insurance","بیمه عمر",["lebensversicherung","life insurance","بیمه عمر"]),
    ("finance","صورتحساب بانکی",["kontoauszug","bank statement","account statement","گردش حساب","صورتحساب بانکی","صورت حساب بانکی"]),
    ("finance","نامه بانکی",["mittelherkunft","bankbestätigung","bank confirmation","نامه بانک","گواهی بانکی"]),
    ("education","مدرک دانشگاهی",["university","universität","hochschule","degree","diploma","transcript","دانشگاه","دانشنامه","ریز نمرات"]),
    ("employment","قرارداد کاری",["arbeitsvertrag","dienstvertrag","employment contract","قرارداد کار","قرارداد استخدام"]),
    ("employment","فیش حقوقی",["gehaltsabrechnung","lohnabrechnung","payslip","salary slip","فیش حقوق"]),
    ("tax","سند مالیاتی",["finanzamt","steuerbescheid","tax office","مالیات"]),
    ("invoice","فاکتور",["invoice","rechnung","faktura","فاکتور"]),
    ("contract","قرارداد",["vertrag","agreement","contract","قرارداد"]),
]
ISSUERS=[
    ("MA35",["ma35","magistratsabteilung 35"]),
    ("ARAG",["arag"]),
    ("ÖGK",["ögk","österreichische gesundheitskasse"]),
    ("Erste Bank",["erste bank","sparkasse"]),
    ("Finanzamt Österreich",["finanzamt österreich"]),
]

@contextmanager
def db():
    con=sqlite3.connect(DB_PATH,timeout=30)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS documents(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL UNIQUE,
          mime TEXT NOT NULL,
          size INTEGER NOT NULL,
          sha256 TEXT NOT NULL UNIQUE,
          ocr_status TEXT NOT NULL DEFAULT 'pending',
          ocr_text TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'other',
          tags TEXT NOT NULL DEFAULT '',
          suggested_title TEXT,
          suggestion_conf REAL NOT NULL DEFAULT 0,
          favorite INTEGER NOT NULL DEFAULT 0,
          deleted INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'upload',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shares(
          token TEXT PRIMARY KEY,
          document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          downloads INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(deleted);
        CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
        CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
        """)
        try:
            con.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
              USING fts5(id UNINDEXED,title,original_name,ocr_text,tags,category,tokenize='unicode61')""")
        except sqlite3.OperationalError:
            pass
        con.execute("UPDATE documents SET ocr_status='pending' WHERE ocr_status='processing'")

def clean_filename(name):
    return Path(name or "document").name.replace("\x00","")[:240]

def base_title(name):
    stem=Path(clean_filename(name)).stem
    stem=re.sub(r"[_]+"," ",stem)
    stem=re.sub(r"\s+"," ",stem).strip(" .-_")
    return stem or "سند بدون نام"

def is_generic_title(title):
    s=(title or "").strip()
    if not s:return True
    if GENERIC_NAME.match(s):return True
    return bool(re.match(r"^(scan|img|image|document|doc)[ _-]*\d",s,re.I))

def fts_upsert(con,row):
    try:
        con.execute("DELETE FROM documents_fts WHERE id=?",(row["id"],))
        con.execute(
            "INSERT INTO documents_fts(id,title,original_name,ocr_text,tags,category) VALUES(?,?,?,?,?,?)",
            (row["id"],row["title"],row["original_name"],row["ocr_text"] or "",row["tags"] or "",row["category"] or "other")
        )
    except sqlite3.OperationalError:
        pass

def row_dict(row):
    return dict(row) if row else None

def ensure_drive_token(token):
    if not DRIVE_TOKEN or not token or not hmac.compare_digest(token,DRIVE_TOKEN):
        raise HTTPException(401,"Unauthorized")

def hash_and_store(stream:BinaryIO,name:str):
    temp=TMP/f"{uuid.uuid4()}.part"
    sha=hashlib.sha256();total=0
    try:
        with temp.open("wb") as out:
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>MAX_UPLOAD:
                    raise HTTPException(413,"File too large")
                sha.update(chunk);out.write(chunk)
        if total==0:
            raise HTTPException(400,"Empty file")
        mime=magic.from_file(str(temp),mime=True) or "application/octet-stream"
        if mime not in ALLOWED:
            raise HTTPException(415,"Only PDF and image files are allowed")
        digest=sha.hexdigest()
        with db() as con:
            prior=con.execute("SELECT id FROM documents WHERE sha256=?",(digest,)).fetchone()
            if prior:
                temp.unlink(missing_ok=True)
                return {"duplicate":True,"id":prior["id"]}
        ext=Path(name).suffix.lower()
        if len(ext)>12:ext=""
        stored=f"{uuid.uuid4()}{ext}"
        temp.replace(FILES/stored)
        return {"duplicate":False,"stored":stored,"mime":mime,"size":total,"sha256":digest}
    except Exception:
        temp.unlink(missing_ok=True)
        raise

def ingest_upload(upload:UploadFile,source="upload"):
    name=clean_filename(upload.filename or "document")
    saved=hash_and_store(upload.file,name)
    if saved.get("duplicate"):
        return {"ok":True,"duplicate":True,"id":saved["id"]}
    did=str(uuid.uuid4());ts=now();title=base_title(name)
    with db() as con:
        con.execute("""INSERT INTO documents
          (id,title,original_name,stored_name,mime,size,sha256,ocr_status,ocr_text,category,tags,suggested_title,suggestion_conf,favorite,deleted,source,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (did,title,name,saved["stored"],saved["mime"],saved["size"],saved["sha256"],"pending","","other","",None,0,0,0,source,ts,ts))
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        fts_upsert(con,row)
    return {"ok":True,"duplicate":False,"id":did,"name":name,"bytes":saved["size"],"queued":True}

def tesseract_text(path,langs):
    try:
        raw=subprocess.check_output(
            ["tesseract",str(path),"stdout","-l",langs,"--oem","1","--psm","6"],
            stderr=subprocess.DEVNULL,text=True,timeout=90
        )
        return raw.strip()
    except Exception:
        return ""

def pdf_native(path):
    try:
        text="\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:12])
        if len(text.strip())>=250 and sum(c.isalpha() for c in text)>=100:
            return text
    except Exception:
        pass
    return ""

def extract_ocr(path,mime):
    native=pdf_native(path) if mime=="application/pdf" else ""
    if native:return native
    texts=[]
    if mime=="application/pdf":
        with tempfile.TemporaryDirectory() as td:
            prefix=str(Path(td)/"page")
            try:
                subprocess.run(["pdftoppm","-f","1","-l","8","-png","-r","260",str(path),prefix],
                               check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180)
            except Exception:
                return ""
            images=sorted(Path(td).glob("page-*.png"))
            for img in images:
                fa=tesseract_text(img,"fas")
                lat=tesseract_text(img,"eng+deu")
                if fa:texts.append(fa)
                if lat:texts.append(lat)
    elif mime.startswith("image/"):
        fa=tesseract_text(path,"fas")
        lat=tesseract_text(path,"eng+deu")
        if fa:texts.append(fa)
        if lat:texts.append(lat)
    return "\n".join(texts)

def normalize(text):
    return re.sub(r"\s+"," ",(text or "").lower()).strip()

def smart_metadata(text):
    t=normalize(text)
    best=None
    for category,label,keys in CATEGORY_RULES:
        hits=[k for k in keys if k.lower() in t]
        score=len(hits)
        if hits and (best is None or score>best[0]):
            best=(score,category,label,hits)
    if not best:
        return {"category":"other","suggested_title":None,"confidence":0}
    score,category,label,hits=best
    issuer=None
    for issuer_name,keys in ISSUERS:
        if any(k.lower() in t for k in keys):
            issuer=issuer_name;break
    number=None
    pats=[
        r"(?:passport|reisepass|گذرنامه)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([a-z0-9-]{5,16})",
        r"(?:invoice|rechnung|فاکتور)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([a-z0-9\-/]{3,20})",
        r"(?:aktenzeichen|geschäftszahl|reference|شماره پرونده)\s*[:#-]?\s*([a-z0-9\-/.]{4,30})",
    ]
    for p in pats:
        m=re.search(p,t,re.I)
        if m:
            number=m.group(1).upper();break
    parts=[label]
    if issuer and issuer.lower() not in label.lower():parts.append(issuer)
    if number:parts.append(number)
    title=" - ".join(parts)
    confidence=min(0.98,0.58+0.12*score+(0.08 if issuer else 0)+(0.08 if number else 0))
    return {"category":category,"suggested_title":title,"confidence":confidence}

def process_one():
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE deleted=0 AND ocr_status='pending' ORDER BY created_at LIMIT 1").fetchone()
        if not row:return False
        con.execute("UPDATE documents SET ocr_status='processing',updated_at=? WHERE id=?",(now(),row["id"]))
    path=FILES/row["stored_name"]
    try:
        text=extract_ocr(path,row["mime"])
        meta=smart_metadata(text)
        title=row["title"]
        if is_generic_title(title) and meta["suggested_title"] and meta["confidence"]>=0.70:
            title=meta["suggested_title"]
        status="done" if text else "empty"
        with db() as con:
            con.execute("""UPDATE documents SET title=?,ocr_text=?,ocr_status=?,category=?,suggested_title=?,suggestion_conf=?,updated_at=? WHERE id=?""",
                        (title,text,status,meta["category"],meta["suggested_title"],meta["confidence"],now(),row["id"]))
            fresh=con.execute("SELECT * FROM documents WHERE id=?",(row["id"],)).fetchone()
            fts_upsert(con,fresh)
    except Exception as e:
        with db() as con:
            con.execute("UPDATE documents SET ocr_status='failed',updated_at=? WHERE id=?",(now(),row["id"]))
        print("ocr:",row["id"],e,flush=True)
    return True

STOP=threading.Event()
def worker():
    while not STOP.is_set():
        try:
            if not process_one():STOP.wait(2)
        except Exception as e:
            print("worker:",e,flush=True);STOP.wait(3)

@asynccontextmanager
async def lifespan(app):
    init_db()
    th=threading.Thread(target=worker,daemon=True,name="archive-ocr")
    th.start()
    yield
    STOP.set()

app=FastAPI(title="Hossein Archive",version="3.1",lifespan=lifespan)

@app.get("/health")
def health():
    with db() as con:
        con.execute("SELECT 1").fetchone()
    return {"status":"ok","app":"hossein-archive","version":"3.1","storage":"local","storage_path":str(ROOT)}

@app.get("/",response_class=HTMLResponse)
def home():
    return (WEB/"index.html").read_text(encoding="utf-8")

@app.get("/api/stats")
def stats(archive_session:str|None=Cookie(None)):
    with db() as con:
        return {
            "documents":con.execute("SELECT count(*) FROM documents WHERE deleted=0").fetchone()[0],
            "favorites":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND favorite=1").fetchone()[0],
            "uncategorized":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND category='other'").fetchone()[0],
            "trash":con.execute("SELECT count(*) FROM documents WHERE deleted=1").fetchone()[0],
            "storage":con.execute("SELECT coalesce(sum(size),0) FROM documents WHERE deleted=0").fetchone()[0],
            "processing":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND ocr_status IN ('pending','processing')").fetchone()[0],
        }

@app.get("/api/documents")
def documents(q:str="",category:str="",scope:str="all",sort:str="newest"):
    where=["1=1"];args=[]
    where.append("deleted=?" );args.append(1 if scope=="trash" else 0)
    if scope=="favorites":where.append("favorite=1")
    if scope=="uncategorized":where.append("category='other'")
    if category:
        where.append("category=?");args.append(category)
    if q.strip():
        tokens=re.findall(r"[\w\u0600-\u06ff-]+",q,re.UNICODE)
        ids=[]
        if tokens:
            try:
                match=" AND ".join(f'"{x.replace(chr(34),"")}"*' for x in tokens[:10])
                with db() as con:
                    ids=[r[0] for r in con.execute("SELECT id FROM documents_fts WHERE documents_fts MATCH ? LIMIT 500",(match,))]
            except Exception:
                ids=[]
        if ids:
            where.append("id IN (%s)"%(",".join("?"*len(ids))))
            args.extend(ids)
        else:
            x=f"%{q.strip()}%"
            where.append("(title LIKE ? OR original_name LIKE ? OR ocr_text LIKE ? OR tags LIKE ?)")
            args.extend([x,x,x,x])
    order={"newest":"created_at DESC","oldest":"created_at ASC","name":"title COLLATE NOCASE ASC","size":"size DESC"}.get(sort,"created_at DESC")
    sql=f"""SELECT id,title,original_name,mime,size,ocr_status,category,tags,suggested_title,suggestion_conf,favorite,deleted,source,created_at,updated_at
            FROM documents WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 500"""
    with db() as con:
        rows=[dict(r) for r in con.execute(sql,args)]
    return {"items":rows,"count":len(rows)}

@app.get("/api/documents/{did}")
def document(did:str):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        d=dict(row);d["ocr_text"]=(d["ocr_text"] or "")[:30000]
        return d

@app.post("/api/documents/upload")
def upload(files:list[UploadFile]=File(...)):
    out=[]
    for f in files[:50]:
        out.append(ingest_upload(f,"upload"))
    return {"ok":True,"items":out}

@app.post("/api/google-drive-push/upload")
def drive_upload(file:UploadFile=File(...),x_drive_token:str|None=Header(None,alias="X-Drive-Token"),x_drive_file_id:str|None=Header(None,alias="X-Drive-File-Id")):
    ensure_drive_token(x_drive_token)
    result=ingest_upload(file,"google_drive")
    result["drive_file_id"]=x_drive_file_id
    return result

@app.patch("/api/documents/{did}")
def update_document(did:str,payload:dict=Body(...)):
    allowed={"title","category","tags","favorite"}
    updates=[];args=[]
    for k,v in payload.items():
        if k not in allowed:continue
        if k=="favorite":v=1 if bool(v) else 0
        updates.append(f"{k}=?");args.append(v)
    if not updates:return {"ok":True}
    updates.append("updated_at=?");args.append(now());args.append(did)
    with db() as con:
        con.execute(f"UPDATE documents SET {','.join(updates)} WHERE id=?",args)
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        fts_upsert(con,row)
    return {"ok":True,"item":dict(row)}

@app.post("/api/documents/{did}/apply-suggestion")
def apply_suggestion(did:str):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        if not row["suggested_title"]:raise HTTPException(400,"No suggestion")
        con.execute("UPDATE documents SET title=?,updated_at=? WHERE id=?",(row["suggested_title"],now(),did))
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone();fts_upsert(con,row)
    return {"ok":True}

@app.delete("/api/documents/{did}")
def trash_document(did:str):
    with db() as con:
        con.execute("UPDATE documents SET deleted=1,updated_at=? WHERE id=?",(now(),did))
    return {"ok":True}

@app.post("/api/documents/{did}/restore")
def restore_document(did:str):
    with db() as con:
        con.execute("UPDATE documents SET deleted=0,updated_at=? WHERE id=?",(now(),did))
    return {"ok":True}

@app.delete("/api/documents/{did}/permanent")
def permanent_delete(did:str):
    with db() as con:
        row=con.execute("SELECT stored_name FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        con.execute("DELETE FROM shares WHERE document_id=?",(did,))
        try:con.execute("DELETE FROM documents_fts WHERE id=?",(did,))
        except Exception:pass
        con.execute("DELETE FROM documents WHERE id=?",(did,))
    (FILES/row["stored_name"]).unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/documents/{did}/file")
def file_view(did:str,download:int=0):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not row:raise HTTPException(404)
    path=FILES/row["stored_name"]
    if not path.exists():raise HTTPException(404)
    disp="attachment" if download else "inline"
    return FileResponse(path,media_type=row["mime"],filename=row["original_name"],content_disposition_type=disp)

@app.post("/api/documents/{did}/share")
def create_share(did:str,payload:dict=Body(default={})):
    days=max(1,min(int(payload.get("days",7)),365))
    token=secrets.token_urlsafe(24)
    exp=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
    with db() as con:
        if not con.execute("SELECT 1 FROM documents WHERE id=? AND deleted=0",(did,)).fetchone():raise HTTPException(404)
        con.execute("INSERT INTO shares(token,document_id,expires_at,created_at,downloads) VALUES(?,?,?,?,0)",(token,did,exp,now()))
    return {"ok":True,"token":token,"url":f"/s/{token}","expires_at":exp}

def shared_row(token):
    with db() as con:
        row=con.execute("""SELECT s.token,s.expires_at,s.downloads,d.* FROM shares s JOIN documents d ON d.id=s.document_id
                           WHERE s.token=? AND d.deleted=0""",(token,)).fetchone()
    if not row:raise HTTPException(404)
    if datetime.fromisoformat(row["expires_at"])<datetime.now(timezone.utc):raise HTTPException(410,"Link expired")
    return row

@app.get("/s/{token}",response_class=HTMLResponse)
def shared_page(token:str):
    row=shared_row(token)
    title=(row["title"] or "Shared document").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return f"""<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>{title}</title><style>body{{font-family:system-ui;background:#0b1020;color:#eef2ff;margin:0}}header{{padding:18px 24px;background:#111831}}
    main{{height:calc(100vh - 70px)}}iframe,img{{width:100%;height:100%;border:0;object-fit:contain;background:white}}a{{color:#9ec5ff}}</style>
    <header><b>{title}</b> · <a href='/shared/{token}/file?download=1'>دانلود</a></header>
    <main><iframe src='/shared/{token}/file'></iframe></main></html>"""

@app.get("/shared/{token}/file")
def shared_file(token:str,download:int=0):
    row=shared_row(token)
    path=FILES/row["stored_name"]
    if not path.exists():raise HTTPException(404)
    with db() as con:
        con.execute("UPDATE shares SET downloads=downloads+1 WHERE token=?",(token,))
    return FileResponse(path,media_type=row["mime"],filename=row["original_name"],content_disposition_type="attachment" if download else "inline")

@app.get("/api/categories")
def categories(archive_session:str|None=Cookie(None)):
    return {"items":[
        {"id":"other","name":"بدون دسته"},
        {"id":"identity","name":"هویتی"},
        {"id":"legal","name":"حقوقی"},
        {"id":"housing","name":"مسکن"},
        {"id":"insurance","name":"بیمه"},
        {"id":"finance","name":"مالی"},
        {"id":"education","name":"تحصیلی"},
        {"id":"employment","name":"شغلی"},
        {"id":"tax","name":"مالیاتی"},
        {"id":"invoice","name":"فاکتور"},
        {"id":"contract","name":"قرارداد"}
    ]}

from document_analyzer import analyze_document
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
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

import magic
from fastapi import Body, Cookie, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from pypdf import PdfReader
from PIL import Image

ROOT=Path(os.getenv("ARCHIVE_ROOT","/data"))
FILES=ROOT/"files"
TMP=ROOT/"tmp"
PREV=ROOT/"previews"
DB_PATH=ROOT/"archive.db"
WEB=Path(__file__).parent/"web"
MAX_UPLOAD=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","").rstrip("/")
COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true"
for p in (ROOT,FILES,TMP,PREV): p.mkdir(parents=True,exist_ok=True)

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
          notes TEXT NOT NULL DEFAULT '',
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
          downloads INTEGER NOT NULL DEFAULT 0,
          max_downloads INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(deleted);
        CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
        CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
        CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
        """)
        dcols={r["name"] for r in con.execute("PRAGMA table_info(documents)")}
        if "notes" not in dcols:
            con.execute("ALTER TABLE documents ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        document_migrations={
            "smart_filename":"TEXT NOT NULL DEFAULT ''",
            "description_fa":"TEXT NOT NULL DEFAULT ''",
            "description_de":"TEXT NOT NULL DEFAULT ''",
            "document_type":"TEXT NOT NULL DEFAULT ''",
            "ai_confidence":"REAL NOT NULL DEFAULT 0",
            "extracted_entities":"TEXT NOT NULL DEFAULT '{}'",
        }
        for column,declaration in document_migrations.items():
            if column not in dcols:
                con.execute(f"ALTER TABLE documents ADD COLUMN {column} {declaration}")
        scols={r["name"] for r in con.execute("PRAGMA table_info(shares)")}
        if "max_downloads" not in scols:
            con.execute("ALTER TABLE shares ADD COLUMN max_downloads INTEGER NOT NULL DEFAULT 0")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS audit_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          action TEXT NOT NULL,
          document_id TEXT,
          source TEXT NOT NULL DEFAULT 'system',
          details TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
        CREATE TABLE IF NOT EXISTS app_settings(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """)
        try:
            con.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts2
              USING fts5(id UNINDEXED,title,original_name,ocr_text,tags,category,notes,tokenize='unicode61')""")
            con.execute("DELETE FROM documents_fts2")
            for row in con.execute("SELECT * FROM documents"):
                con.execute(
                    "INSERT INTO documents_fts2(id,title,original_name,ocr_text,tags,category,notes) VALUES(?,?,?,?,?,?,?)",
                    (row["id"],row["title"],row["original_name"],row["ocr_text"] or "",row["tags"] or "",row["category"] or "other",row["notes"] or "")
                )
        except sqlite3.OperationalError:
            pass
        con.execute("UPDATE documents SET ocr_status='pending' WHERE ocr_status='processing'")

def clean_filename(name):
    return Path(name or "document").name.replace("\x00","")[:240]

def audit(action,document_id=None,source="system",details=""):
    try:
        with db() as con:
            con.execute(
                "INSERT INTO audit_events(action,document_id,source,details,created_at) VALUES(?,?,?,?,?)",
                (str(action)[:80],document_id,str(source)[:80],str(details)[:1000],now())
            )
    except Exception as exc:
        print("audit:",exc,flush=True)

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


def make_preview(path:Path,mime:str,did:str):
    out=PREV/f"{did}.jpg"
    try:
        if mime=="application/pdf":
            with tempfile.TemporaryDirectory() as td:
                base=str(Path(td)/"preview")
                subprocess.run(
                    ["pdftoppm","-f","1","-singlefile","-jpeg","-scale-to","1000",str(path),base],
                    check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45
                )
                src=Path(base+".jpg")
                if src.exists(): shutil.copy2(src,out)
        elif mime.startswith("image/"):
            im=Image.open(path)
            im.thumbnail((1000,1200))
            canvas=Image.new("RGB",im.size,"white")
            if im.mode in ("RGBA","LA"):
                canvas.paste(im,(0,0),im.getchannel("A"))
            else:
                canvas.paste(im.convert("RGB"),(0,0))
            canvas.save(out,"JPEG",quality=84,optimize=True)
        return out.exists()
    except Exception as e:
        print("preview:",did,e,flush=True)
        return False

def make_snippet(text:str,q:str,limit:int=180):
    text=re.sub(r"\s+"," ",text or "").strip()
    if not text:return ""
    if not q:return text[:limit]
    low=text.lower();need=q.lower().strip()
    pos=low.find(need)
    if pos<0:
        for token in re.findall(r"[\w\u0600-\u06ff-]+",need,re.UNICODE):
            pos=low.find(token)
            if pos>=0:break
    if pos<0:return text[:limit]
    start=max(0,pos-limit//3);end=min(len(text),start+limit)
    return ("…" if start else "")+text[start:end]+("…" if end<len(text) else "")

def fts_upsert(con,row):
    try:
        con.execute("DELETE FROM documents_fts2 WHERE id=?",(row["id"],))
        con.execute(
            "INSERT INTO documents_fts2(id,title,original_name,ocr_text,tags,category,notes) VALUES(?,?,?,?,?,?,?)",
            (row["id"],row["title"],row["original_name"],row["ocr_text"] or "",row["tags"] or "",row["category"] or "other",row["notes"] or "")
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
    audit("document_ingested",did,source,name)
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
        make_preview(path,row["mime"],row["id"])
        text=extract_ocr(path,row["mime"])
        meta=smart_metadata(text)
        analysis=analyze_document(text,row["original_name"])
        title=row["title"]
        if is_generic_title(title) and meta["suggested_title"] and meta["confidence"]>=0.70:
            title=meta["suggested_title"]
        status="done" if text else "empty"
        with db() as con:
            con.execute("""UPDATE documents SET 
title=?,
ocr_text=?,
ocr_status=?,
category=?,
suggested_title=?,
suggestion_conf=?,
smart_filename=?,
description_fa=?,
description_de=?,
document_type=?,
ai_confidence=?,
extracted_entities=?,
updated_at=?
WHERE id=?""",
                        (
                        title,
                        text,
                        status,
                        meta["category"],
                        analysis["smart_filename"],
                        analysis["ai_confidence"],
                        analysis["smart_filename"],
                        analysis["description_fa"],
                        analysis["description_de"],
                        analysis["document_type"],
                        analysis["ai_confidence"],
                        analysis["extracted_entities"],
                        now(),
                        row["id"]
                        ))
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

app=FastAPI(title="Hossein Archive",version="4.1",lifespan=lifespan)

@app.get("/health")
def health():
    with db() as con:
        con.execute("SELECT 1").fetchone()
    return {"status":"ok","app":"hossein-archive","version":"4.1","storage":"local","storage_path":str(ROOT)}

@app.get("/",response_class=HTMLResponse)
def home():
    return (WEB/"index.html").read_text(encoding="utf-8")

@app.get("/api/stats")
def stats():
    with db() as con:
        return {
            "documents":con.execute("SELECT count(*) FROM documents WHERE deleted=0").fetchone()[0],
            "favorites":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND favorite=1").fetchone()[0],
            "uncategorized":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND category='other'").fetchone()[0],
            "trash":con.execute("SELECT count(*) FROM documents WHERE deleted=1").fetchone()[0],
            "storage":con.execute("SELECT coalesce(sum(size),0) FROM documents WHERE deleted=0").fetchone()[0],
            "processing":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND ocr_status IN ('pending','processing')").fetchone()[0],
            "shares":con.execute("SELECT count(*) FROM shares WHERE expires_at>?",(now(),)).fetchone()[0],
            "scanner":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND source='scanner_folder'").fetchone()[0],
            "telegram":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND source='telegram'").fetchone()[0],
            "failed":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND ocr_status='failed'").fetchone()[0],
        }

@app.get("/api/documents")
def documents(q:str="",category:str="",source:str="",ocr:str="",days:int=0,scope:str="all",sort:str="newest"):
    where=["1=1"];args=[]
    where.append("deleted=?");args.append(1 if scope=="trash" else 0)
    if scope=="favorites":where.append("favorite=1")
    if scope=="uncategorized":where.append("category='other'")
    if category:
        where.append("category=?");args.append(category)
    if source in ("upload","google_drive","scanner_folder","telegram"):
        where.append("source=?");args.append(source)
    if ocr in ("pending","processing","done","empty","failed"):
        where.append("ocr_status=?");args.append(ocr)
    if days in (1,7,30,90,365):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        where.append("created_at>=?");args.append(cutoff)
    if q.strip():
        tokens=re.findall(r"[\w\u0600-\u06ff-]+",q,re.UNICODE)
        ids=[]
        if tokens:
            try:
                match=" AND ".join(f'"{x.replace(chr(34),"")}"*' for x in tokens[:10])
                with db() as con:
                    ids=[r[0] for r in con.execute("SELECT id FROM documents_fts2 WHERE documents_fts2 MATCH ? LIMIT 500",(match,))]
            except Exception:
                ids=[]
        if ids:
            where.append("id IN (%s)"%(",".join("?"*len(ids))))
            args.extend(ids)
        else:
            x=f"%{q.strip()}%"
            where.append("(title LIKE ? OR original_name LIKE ? OR ocr_text LIKE ? OR tags LIKE ? OR notes LIKE ?)")
            args.extend([x,x,x,x,x])
    order={"newest":"created_at DESC","oldest":"created_at ASC","name":"title COLLATE NOCASE ASC","size":"size DESC"}.get(sort,"created_at DESC")
    sql=f"""SELECT id,title,original_name,mime,size,ocr_status,category,tags,suggested_title,suggestion_conf,favorite,deleted,source,created_at,updated_at,ocr_text
            FROM documents WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 500"""
    with db() as con:
        rows=[]
        for r in con.execute(sql,args):
            d=dict(r)
            d["snippet"]=make_snippet(d.pop("ocr_text",""),q) if q.strip() else ""
            d["has_preview"]=(PREV/f'{d["id"]}.jpg').exists()
            rows.append(d)
    return {"items":rows,"count":len(rows)}

@app.get("/api/documents/{did}")
def document(did:str):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        d=dict(row);d["ocr_text"]=(d["ocr_text"] or "")[:30000]
        return d

@app.post("/api/documents/upload")
def upload(files:list[UploadFile]=File(...),x_archive_source:str|None=Header(None,alias="X-Archive-Source")):
    source=x_archive_source if x_archive_source in ("upload","scanner_folder","telegram") else "upload"
    out=[]
    for f in files[:50]:
        out.append(ingest_upload(f,source))
    return {"ok":True,"items":out}

@app.post("/api/google-drive-push/upload")
def drive_upload(file:UploadFile=File(...),x_drive_token:str|None=Header(None,alias="X-Drive-Token"),x_drive_file_id:str|None=Header(None,alias="X-Drive-File-Id")):
    ensure_drive_token(x_drive_token)
    result=ingest_upload(file,"google_drive")
    result["drive_file_id"]=x_drive_file_id
    return result

@app.patch("/api/documents/{did}")
def update_document(did:str,payload:dict=Body(...)):
    allowed={"title","category","tags","notes","favorite","filename"}
    updates=[];args=[]
    with db() as con:
        current=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not current:raise HTTPException(404)
    for k,v in payload.items():
        if k not in allowed:continue
        if k=="favorite":v=1 if bool(v) else 0
        if k=="filename":
            requested=clean_filename(str(v or "").strip())
            if not requested:raise HTTPException(400,"Filename is required")
            original_ext=Path(current["original_name"]).suffix
            requested_stem=Path(requested).stem.strip(" .-_")
            if not requested_stem:raise HTTPException(400,"Invalid filename")
            v=(requested_stem+original_ext)[:240]
            updates.extend(["original_name=?","smart_filename=?"]);args.extend([v,v])
            continue
        updates.append(f"{k}=?");args.append(v)
    if not updates:return {"ok":True}
    updates.append("updated_at=?");args.append(now());args.append(did)
    with db() as con:
        con.execute(f"UPDATE documents SET {','.join(updates)} WHERE id=?",args)
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        fts_upsert(con,row)
    audit("document_updated",did,"web",",".join(updates))
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
    audit("document_trashed",did,"web")
    return {"ok":True}

@app.post("/api/documents/{did}/restore")
def restore_document(did:str):
    with db() as con:
        con.execute("UPDATE documents SET deleted=0,updated_at=? WHERE id=?",(now(),did))
    audit("document_restored",did,"web")
    return {"ok":True}

@app.delete("/api/documents/{did}/permanent")
def permanent_delete(did:str):
    with db() as con:
        row=con.execute("SELECT stored_name FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        con.execute("DELETE FROM shares WHERE document_id=?",(did,))
        try:con.execute("DELETE FROM documents_fts2 WHERE id=?",(did,))
        except Exception:pass
        con.execute("DELETE FROM documents WHERE id=?",(did,))
    (FILES/row["stored_name"]).unlink(missing_ok=True)
    (PREV/f"{did}.jpg").unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/documents/{did}/preview")
def preview_file(did:str):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not row:raise HTTPException(404)
    out=PREV/f"{did}.jpg"
    if not out.exists():
        path=FILES/row["stored_name"]
        if not path.exists() or not make_preview(path,row["mime"],did):
            raise HTTPException(404)
    return FileResponse(out,media_type="image/jpeg",headers={"Cache-Control":"private,max-age=3600"})

@app.post("/api/documents/{did}/retry-ocr")
def retry_ocr(did:str):
    with db() as con:
        row=con.execute("SELECT id FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        con.execute("UPDATE documents SET ocr_status='pending',updated_at=? WHERE id=?",(now(),did))
    return {"ok":True}

@app.get("/api/documents/{did}/file")
def file_view(did:str,download:int=0):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not row:raise HTTPException(404)
    path=FILES/row["stored_name"]
    if not path.exists():raise HTTPException(404)
    disp="attachment" if download else "inline"
    extension=Path(row["original_name"]).suffix.lower() or Path(row["stored_name"]).suffix.lower()
    preferred=(row["smart_filename"] or "").strip() if "smart_filename" in row.keys() else ""
    if not preferred:
        preferred=re.sub(r"[^\w\u0600-\u06ff.-]+","_",row["title"],flags=re.UNICODE).strip("._")+extension
    return FileResponse(path,media_type=row["mime"],filename=preferred or row["original_name"],content_disposition_type=disp)

@app.get("/api/system/status")
def system_status():
    inbox=ROOT/"inbox"
    with db() as con:
        pending=con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND ocr_status IN ('pending','processing')").fetchone()[0]
        failed=con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND ocr_status='failed'").fetchone()[0]
        last=con.execute("SELECT created_at,action,source,details FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    usage=shutil.disk_usage(ROOT)
    return {
        "version":"4.1",
        "ocr":{"pending":pending,"failed":failed},
        "inbox":{"path":str(inbox),"queued":len(list(inbox.glob('*'))) if inbox.exists() else 0},
        "storage":{"total":usage.total,"used":usage.used,"free":usage.free},
        "telegram":{"configured":bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip())},
        "last_event":dict(last) if last else None,
    }

@app.get("/api/activity")
def activity(limit:int=100):
    limit=max(1,min(limit,500))
    with db() as con:
        rows=[dict(r) for r in con.execute(
            "SELECT id,action,document_id,source,details,created_at FROM audit_events ORDER BY id DESC LIMIT ?",(limit,)
        )]
    return {"items":rows}

@app.post("/api/documents/{did}/share")
def create_share(did:str,payload:dict=Body(default={})):
    days=max(1,min(int(payload.get("days",7)),365))
    max_downloads=max(0,min(int(payload.get("max_downloads",0) or 0),10000))
    token=secrets.token_urlsafe(24)
    exp=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
    with db() as con:
        if not con.execute("SELECT 1 FROM documents WHERE id=? AND deleted=0",(did,)).fetchone():raise HTTPException(404)
        con.execute("INSERT INTO shares(token,document_id,expires_at,created_at,downloads,max_downloads) VALUES(?,?,?,?,0,?)",(token,did,exp,now(),max_downloads))
    rel=f"/s/{token}"
    return {"ok":True,"token":token,"url":rel,"share_url":(PUBLIC_BASE_URL+rel if PUBLIC_BASE_URL else rel),"expires_at":exp,"max_downloads":max_downloads}


@app.get("/api/documents/{did}/shares")
def list_shares(did:str):
    with db() as con:
        rows=[dict(r) for r in con.execute(
            "SELECT token,expires_at,created_at,downloads,max_downloads FROM shares WHERE document_id=? ORDER BY created_at DESC",(did,)
        )]
    current=datetime.now(timezone.utc)
    for x in rows:
        x["url"]=f'/s/{x["token"]}'
        x["share_url"]=(PUBLIC_BASE_URL+x["url"] if PUBLIC_BASE_URL else x["url"])
        x["expired"]=datetime.fromisoformat(x["expires_at"])<current
        x["exhausted"]=bool(x["max_downloads"] and x["downloads"]>=x["max_downloads"])
    return {"items":rows}

@app.delete("/api/shares/{token}")
def revoke_share(token:str):
    with db() as con:
        con.execute("DELETE FROM shares WHERE token=?",(token,))
    return {"ok":True}

def shared_row(token):
    with db() as con:
        row=con.execute("""SELECT s.token,s.expires_at,s.downloads,s.max_downloads,d.* FROM shares s JOIN documents d ON d.id=s.document_id
                           WHERE s.token=? AND d.deleted=0""",(token,)).fetchone()
    if not row:raise HTTPException(404)
    if datetime.fromisoformat(row["expires_at"])<datetime.now(timezone.utc):raise HTTPException(410,"Link expired")
    if row["max_downloads"] and row["downloads"]>=row["max_downloads"]:raise HTTPException(410,"Download limit reached")
    return row

@app.get("/s/{token}",response_class=HTMLResponse)
def shared_page(token:str):
    row=shared_row(token)
    def eh(s):
        return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
    title=eh(row["title"] or "Shared document")
    original=eh(row["original_name"])
    expires=eh(row["expires_at"][:10])
    usage=(f'{row["downloads"]}/{row["max_downloads"]}' if row["max_downloads"] else f'{row["downloads"]}')
    return f"""<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <meta name='theme-color' content='#0b1224'><title>{title}</title><style>
    *{{box-sizing:border-box}}body{{font-family:Tahoma,Arial,system-ui;background:#0b1224;color:#eef3ff;margin:0}}
    header{{padding:14px 18px;background:#111a31;display:flex;align-items:center;justify-content:space-between;gap:12px;position:sticky;top:0;z-index:2}}
    .meta{{min-width:0}}h1{{font-size:16px;margin:0 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}small{{color:#98a6bd;direction:auto;display:block}}
    .actions{{display:flex;gap:8px}}a{{text-decoration:none}}.btn{{display:inline-block;border-radius:10px;padding:9px 12px;background:#2868f0;color:white;font-weight:700}}
    .secondary{{background:#1b2944;color:#dce6f8}}main{{height:calc(100vh - 78px);background:#202a3c}}iframe{{width:100%;height:100%;border:0;background:white}}
    .info{{position:fixed;bottom:12px;left:12px;background:#0d1730de;border:1px solid #ffffff1a;border-radius:10px;padding:7px 10px;font-size:10px;color:#aebbd0}}
    @media(max-width:650px){{header{{align-items:flex-start;flex-direction:column}}.actions{{width:100%}}.btn{{flex:1;text-align:center}}main{{height:calc(100vh - 126px)}}}}
    </style></head><body>
    <header><div class='meta'><h1>{title}</h1><small>{original}</small></div><div class='actions'><a class='btn secondary' href='/shared/{token}/file' target='_blank'>باز کردن</a><a class='btn' href='/shared/{token}/file?download=1'>دانلود</a></div></header>
    <main><iframe src='/shared/{token}/file'></iframe></main>
    <div class='info'>اعتبار تا {expires} · دانلود: {usage}</div>
    </body></html>"""

@app.get("/shared/{token}/file")
def shared_file(token:str,download:int=0):
    row=shared_row(token)
    path=FILES/row["stored_name"]
    if not path.exists():raise HTTPException(404)
    if download:
        with db() as con:
            con.execute("UPDATE shares SET downloads=downloads+1 WHERE token=?",(token,))
    return FileResponse(path,media_type=row["mime"],filename=row["original_name"],content_disposition_type="attachment" if download else "inline")


@app.get("/api/tags")
def tags():
    counts={}
    with db() as con:
        for row in con.execute("SELECT tags FROM documents WHERE deleted=0 AND tags<>''"):
            for tag in re.split(r"[,،]",row["tags"] or ""):
                t=tag.strip()
                if t:counts[t]=counts.get(t,0)+1
    items=sorted(({"name":k,"count":v} for k,v in counts.items()),key=lambda x:(-x["count"],x["name"].lower()))[:100]
    return {"items":items}

@app.post("/api/bulk")
def bulk(payload:dict=Body(...)):
    ids=[str(x) for x in payload.get("ids",[]) if x][:200]
    action=str(payload.get("action",""))
    if not ids:raise HTTPException(400,"No documents selected")
    marks=",".join("?" for _ in ids)
    with db() as con:
        if action=="favorite":
            con.execute(f"UPDATE documents SET favorite=1,updated_at=? WHERE id IN ({marks})",[now(),*ids])
        elif action=="unfavorite":
            con.execute(f"UPDATE documents SET favorite=0,updated_at=? WHERE id IN ({marks})",[now(),*ids])
        elif action=="trash":
            con.execute(f"UPDATE documents SET deleted=1,updated_at=? WHERE id IN ({marks})",[now(),*ids])
        elif action=="restore":
            con.execute(f"UPDATE documents SET deleted=0,updated_at=? WHERE id IN ({marks})",[now(),*ids])
        elif action=="category":
            category=str(payload.get("category","other"))[:100]
            con.execute(f"UPDATE documents SET category=?,updated_at=? WHERE id IN ({marks})",[category,now(),*ids])
        else:
            raise HTTPException(400,"Unsupported bulk action")
        rows=list(con.execute(f"SELECT * FROM documents WHERE id IN ({marks})",ids))
        for row in rows:fts_upsert(con,row)
    return {"ok":True,"count":len(ids)}

@app.post("/api/export")
def export_documents(payload:dict=Body(...)):
    ids=[str(x) for x in payload.get("ids",[]) if x][:200]
    if not ids:raise HTTPException(400,"No documents selected")
    marks=",".join("?" for _ in ids)
    with db() as con:
        rows=list(con.execute(f"SELECT id,title,original_name,stored_name FROM documents WHERE deleted=0 AND id IN ({marks})",ids))
    if not rows:raise HTTPException(404)
    out=TMP/f"export-{uuid.uuid4()}.zip"
    used=set()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for row in rows:
            path=FILES/row["stored_name"]
            if not path.exists():continue
            name=clean_filename(row["original_name"])
            base=Path(name).stem
            ext=Path(name).suffix
            candidate=name;i=2
            while candidate.lower() in used:
                candidate=f"{base} ({i}){ext}";i+=1
            used.add(candidate.lower())
            z.write(path,candidate)
    return FileResponse(out,media_type="application/zip",filename="Hossein-Archive-Export.zip",background=BackgroundTask(lambda:out.unlink(missing_ok=True)))

@app.get("/icon.svg")
def icon():
    return FileResponse(WEB/"icon.svg",media_type="image/svg+xml",headers={"Cache-Control":"public,max-age=86400"})

@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB/"manifest.webmanifest",media_type="application/manifest+json",headers={"Cache-Control":"no-cache"})

@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB/"sw.js",media_type="application/javascript",headers={"Cache-Control":"no-cache"})

@app.get("/api/categories")
def categories():
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

from document_analyzer import analyze_document
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import socket
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
from urllib.parse import parse_qsl
from urllib.request import Request as URLRequest, urlopen

import magic
from fastapi import Body, Cookie, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from pypdf import PdfReader
from PIL import Image, ImageFilter, ImageOps

ROOT=Path(os.getenv("ARCHIVE_ROOT","/data"))
FILES=ROOT/"files"
TMP=ROOT/"tmp"
PREV=ROOT/"previews"
DB_PATH=ROOT/"archive.db"
WEB=Path(__file__).parent/"web"
MAX_UPLOAD=int(os.getenv("MAX_UPLOAD_MB","100"))*1024*1024
PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","").rstrip("/")
COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true"
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
TELEGRAM_ALLOWED_USERS={x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS","").split(",") if x.strip()}
TELEGRAM_INIT_MAX_AGE=int(os.getenv("TELEGRAM_INIT_MAX_AGE","86400"))
for p in (ROOT,FILES,TMP,PREV): p.mkdir(parents=True,exist_ok=True)

def read_secret(path,env_name):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return os.getenv(env_name,"").strip()

DRIVE_TOKEN=read_secret(os.getenv("DRIVE_PUSH_TOKEN_FILE","/run/secrets/drive_push_token"),"DRIVE_PUSH_TOKEN")
DRIVE_BROWSER_URL=os.getenv("DRIVE_BROWSER_URL","").strip()
ALLOWED={
    "application/pdf","image/jpeg","image/png","image/webp","image/tiff",
    "audio/mpeg","audio/mp3","audio/wav","audio/x-wav","audio/wave",
    "audio/mp4","audio/ogg","audio/webm","video/mp4","video/webm",
    "video/quicktime","video/x-matroska",
}
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

def document_validity(expiry_date):
    if not expiry_date:return "none"
    try:
        expiry=datetime.strptime(str(expiry_date)[:10],"%Y-%m-%d").date()
    except ValueError:
        return "none"
    days=(expiry-datetime.now(timezone.utc).date()).days
    if days<0:return "expired"
    if days<=60:return "expiring"
    return "valid"

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS documents(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL UNIQUE,
          mime TEXT NOT NULL,
          media_kind TEXT NOT NULL DEFAULT 'document',
          size INTEGER NOT NULL,
          sha256 TEXT NOT NULL UNIQUE,
          ocr_status TEXT NOT NULL DEFAULT 'pending',
          ocr_text TEXT NOT NULL DEFAULT '',
          transcript TEXT NOT NULL DEFAULT '',
          transcript_status TEXT NOT NULL DEFAULT 'not_applicable',
          media_metadata TEXT NOT NULL DEFAULT '{}',
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
            "media_kind":"TEXT NOT NULL DEFAULT 'document'",
            "transcript":"TEXT NOT NULL DEFAULT ''",
            "transcript_status":"TEXT NOT NULL DEFAULT 'not_applicable'",
            "media_metadata":"TEXT NOT NULL DEFAULT '{}'",
            "smart_filename":"TEXT NOT NULL DEFAULT ''",
            "source_name":"TEXT NOT NULL DEFAULT ''",
            "filename_locked":"INTEGER NOT NULL DEFAULT 0",
            "description_fa":"TEXT NOT NULL DEFAULT ''",
            "description_de":"TEXT NOT NULL DEFAULT ''",
            "document_type":"TEXT NOT NULL DEFAULT ''",
            "entity_id":"TEXT NOT NULL DEFAULT ''",
            "country":"TEXT NOT NULL DEFAULT ''",
            "ai_confidence":"REAL NOT NULL DEFAULT 0",
            "extracted_entities":"TEXT NOT NULL DEFAULT '{}'",
            "issue_date":"TEXT NOT NULL DEFAULT ''",
            "expiry_date":"TEXT NOT NULL DEFAULT ''",
            "version_no":"INTEGER NOT NULL DEFAULT 1",
            "project_id":"TEXT NOT NULL DEFAULT ''",
            "action_status":"TEXT NOT NULL DEFAULT 'none'",
            "follow_up_at":"TEXT NOT NULL DEFAULT ''",
        }
        for column,declaration in document_migrations.items():
            if column not in dcols:
                con.execute(f"ALTER TABLE documents ADD COLUMN {column} {declaration}")
        con.execute("UPDATE documents SET source_name=original_name WHERE source_name='' OR source_name IS NULL")
        scols={r["name"] for r in con.execute("PRAGMA table_info(shares)")}
        if "max_downloads" not in scols:
            con.execute("ALTER TABLE shares ADD COLUMN max_downloads INTEGER NOT NULL DEFAULT 0")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS entities(
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'person',
          country TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_kind ON entities(name COLLATE NOCASE,kind);
        CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_id);
        CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
        CREATE INDEX IF NOT EXISTS idx_documents_country ON documents(country);
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
        CREATE TABLE IF NOT EXISTS document_versions(
          id TEXT PRIMARY KEY,
          document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          version_no INTEGER NOT NULL,
          stored_name TEXT NOT NULL,
          original_name TEXT NOT NULL,
          mime TEXT NOT NULL,
          size INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_versions_number
          ON document_versions(document_id,version_no);
        CREATE TABLE IF NOT EXISTS entity_requirements(
          id TEXT PRIMARY KEY,
          entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          document_type TEXT NOT NULL,
          country TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_requirements_unique
          ON entity_requirements(entity_id,document_type,country);
        CREATE INDEX IF NOT EXISTS idx_documents_expiry ON documents(expiry_date);
        CREATE TABLE IF NOT EXISTS personal_cases(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'personal',
          status TEXT NOT NULL DEFAULT 'active',
          priority INTEGER NOT NULL DEFAULT 2,
          color TEXT NOT NULL DEFAULT '#5b7cfa',
          notes TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          due_date TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS personal_items(
          id TEXT PRIMARY KEY,
          item_type TEXT NOT NULL DEFAULT 'task',
          title TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'inbox',
          priority INTEGER NOT NULL DEFAULT 2,
          due_at TEXT NOT NULL DEFAULT '',
          follow_up_at TEXT NOT NULL DEFAULT '',
          repeat_rule TEXT NOT NULL DEFAULT '',
          case_id TEXT NOT NULL DEFAULT '',
          document_id TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'manual',
          amount REAL,
          currency TEXT NOT NULL DEFAULT '',
          metadata TEXT NOT NULL DEFAULT '{}',
          completed_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_personal_items_status ON personal_items(status);
        CREATE INDEX IF NOT EXISTS idx_personal_items_due ON personal_items(due_at);
        CREATE INDEX IF NOT EXISTS idx_personal_items_followup ON personal_items(follow_up_at);
        CREATE INDEX IF NOT EXISTS idx_personal_items_case ON personal_items(case_id);
        CREATE TABLE IF NOT EXISTS personal_captures(
          id TEXT PRIMARY KEY,
          raw_text TEXT NOT NULL,
          normalized_hash TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL DEFAULT 'manual',
          status TEXT NOT NULL DEFAULT 'captured',
          suggested_type TEXT NOT NULL DEFAULT 'note',
          suggested_title TEXT NOT NULL DEFAULT '',
          suggested_data TEXT NOT NULL DEFAULT '{}',
          confirmed_item_id TEXT NOT NULL DEFAULT '',
          confirmed_fact_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          confirmed_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_personal_captures_status ON personal_captures(status,created_at DESC);
        CREATE TABLE IF NOT EXISTS personal_projects(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_projects_title ON personal_projects(title COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS personal_links(
          id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
          target_type TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'related',
          confidence INTEGER NOT NULL DEFAULT 100, source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL,
          UNIQUE(source_type,source_id,target_type,target_id,relation)
        );
        CREATE INDEX IF NOT EXISTS idx_personal_links_target ON personal_links(target_type,target_id);
        CREATE TABLE IF NOT EXISTS personal_events(
          id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
          action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_personal_events_subject ON personal_events(subject_type,subject_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS personal_facts(
          id TEXT PRIMARY KEY,
          fact_type TEXT NOT NULL,
          label TEXT NOT NULL,
          value TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          confidence TEXT NOT NULL DEFAULT 'confirmed',
          case_id TEXT NOT NULL DEFAULT '',
          entity_id TEXT NOT NULL DEFAULT '',
          source_capture_id TEXT NOT NULL DEFAULT '',
          fingerprint TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          archived_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_personal_facts_status ON personal_facts(status,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_personal_facts_case ON personal_facts(case_id);
        CREATE TABLE IF NOT EXISTS personal_fact_events(
          id TEXT PRIMARY KEY,
          fact_id TEXT NOT NULL REFERENCES personal_facts(id) ON DELETE CASCADE,
          action TEXT NOT NULL,
          snapshot TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_personal_fact_events_fact ON personal_fact_events(fact_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS work_devices(
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'server',
          site TEXT NOT NULL DEFAULT 'Tehran',
          address TEXT NOT NULL,
          port INTEGER NOT NULL DEFAULT 0,
          protocol TEXT NOT NULL DEFAULT 'tcp',
          enabled INTEGER NOT NULL DEFAULT 1,
          tags TEXT NOT NULL DEFAULT '',
          last_status TEXT NOT NULL DEFAULT 'unknown',
          last_checked_at TEXT NOT NULL DEFAULT '',
          latency_ms REAL,
          details TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_work_devices_enabled ON work_devices(enabled);
        CREATE TABLE IF NOT EXISTS work_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          device_id TEXT,
          kind TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'info',
          message TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_work_events_created ON work_events(created_at DESC);
        CREATE TABLE IF NOT EXISTS work_actions(
          id TEXT PRIMARY KEY,
          device_id TEXT,
          task TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          requested_by TEXT NOT NULL DEFAULT 'web',
          result TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          approved_at TEXT NOT NULL DEFAULT '',
          completed_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_work_actions_status ON work_actions(status,created_at DESC);
        """)
        wa_cols={r["name"] for r in con.execute("PRAGMA table_info(work_actions)")}
        if "parameters" not in wa_cols:
            con.execute("ALTER TABLE work_actions ADD COLUMN parameters TEXT NOT NULL DEFAULT '{}'")
        ccols={r["name"] for r in con.execute("PRAGMA table_info(personal_captures)")}
        if "project_id" not in ccols: con.execute("ALTER TABLE personal_captures ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
        if "suggested_project_id" not in ccols: con.execute("ALTER TABLE personal_captures ADD COLUMN suggested_project_id TEXT NOT NULL DEFAULT ''")
        if "project_confidence" not in ccols: con.execute("ALTER TABLE personal_captures ADD COLUMN project_confidence INTEGER NOT NULL DEFAULT 0")
        icols={r["name"] for r in con.execute("PRAGMA table_info(personal_items)")}
        if "project_id" not in icols: con.execute("ALTER TABLE personal_items ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
        fcols={r["name"] for r in con.execute("PRAGMA table_info(personal_facts)")}
        if "project_id" not in fcols: con.execute("ALTER TABLE personal_facts ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
        pcols={r["name"] for r in con.execute("PRAGMA table_info(personal_projects)")}
        for column,declaration in {
            'goal':"TEXT NOT NULL DEFAULT ''",'next_action':"TEXT NOT NULL DEFAULT ''",
            'due_date':"TEXT NOT NULL DEFAULT ''",'color':"TEXT NOT NULL DEFAULT '#5b6ff7'",
            'priority':"INTEGER NOT NULL DEFAULT 2"}.items():
            if column not in pcols: con.execute(f"ALTER TABLE personal_projects ADD COLUMN {column} {declaration}")
        for title,aliases in [
            ('اقامت اتریش','MA35 Beschwerde وین Niederlassung'),('مسیر ایتالیا و دانشگاه','Italy Italia دانشگاه تحصیل'),
            ('خانه و اجاره وین','خانه اجاره Mietvertrag Wien'),('بیمه و امور بانکی','ARAG ÖGK بیمه Erste بانک'),
            ('خودرو','اریون Aurion ماشین خودرو'),('زمین و املاک','زمین باغ ملک ویلا'),('سفرها','سفر پرواز هتل'),('سلامت و امور شخصی','سلامت پزشک درمان'),('خانواده','خانواده')]:
            con.execute("INSERT OR IGNORE INTO personal_projects(id,title,aliases,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(str(uuid.uuid5(uuid.NAMESPACE_URL,'hossein-project:'+title)),title,aliases,'','active',now(),now()))
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

def upsert_entity(name,kind="person",country=""):
    name=re.sub(r"\s+"," ",str(name or "")).strip()[:160]
    kind=kind if kind in ("person","organization","other") else "other"
    if not name:return ""
    with db() as con:
        row=con.execute("SELECT id,country FROM entities WHERE name=? COLLATE NOCASE AND kind=?",(name,kind)).fetchone()
        if row:
            if country and not row["country"]:con.execute("UPDATE entities SET country=?,updated_at=? WHERE id=?",(country,now(),row["id"]))
            return row["id"]
        eid=str(uuid.uuid4());ts=now()
        con.execute("INSERT INTO entities(id,name,kind,country,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(eid,name,kind,country,"",ts,ts))
        return eid

def base_title(name):
    stem=Path(clean_filename(name)).stem
    stem=re.sub(r"[_]+"," ",stem)
    stem=re.sub(r"\s+"," ",stem).strip(" .-_")
    return stem or "سند بدون نام"

def media_kind_for_mime(mime):
    if mime == "application/pdf": return "document"
    if str(mime).startswith("image/"): return "image"
    if str(mime).startswith("audio/"): return "audio"
    if str(mime).startswith("video/"): return "video"
    return "file"

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
    kind=media_kind_for_mime(saved["mime"])
    transcript_status="pending" if kind in ("audio","video") else "not_applicable"
    ocr_status="pending" if kind in ("document","image") else "skipped"
    with db() as con:
        con.execute("""INSERT INTO documents
          (id,title,original_name,source_name,stored_name,mime,media_kind,size,sha256,ocr_status,ocr_text,transcript,transcript_status,media_metadata,category,tags,suggested_title,suggestion_conf,favorite,deleted,source,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (did,title,name,name,saved["stored"],saved["mime"],kind,saved["size"],saved["sha256"],ocr_status,"","",transcript_status,"{}","other","",None,0,0,0,source,ts,ts))
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        fts_upsert(con,row)
    audit("document_ingested",did,source,name)
    return {"ok":True,"duplicate":False,"id":did,"name":name,"bytes":saved["size"],"queued":True}

def prepare_ocr_image(path,out):
    with Image.open(path) as source:
        image=ImageOps.exif_transpose(source).convert("L")
        width,height=image.size
        longest=max(width,height)
        if longest<2200:
            scale=2200/longest
            image=image.resize((max(1,int(width*scale)),max(1,int(height*scale))),Image.Resampling.LANCZOS)
        elif longest>4200:
            scale=4200/longest
            image=image.resize((max(1,int(width*scale)),max(1,int(height*scale))),Image.Resampling.LANCZOS)
        image=ImageOps.autocontrast(image,cutoff=1)
        image=image.filter(ImageFilter.MedianFilter(size=3))
        image=image.filter(ImageFilter.UnsharpMask(radius=1.5,percent=160,threshold=3))
        image.save(out,"PNG",optimize=True,dpi=(300,300))

def tesseract_text(path,langs="fas+eng+deu"):
    with tempfile.TemporaryDirectory() as td:
        prepared=Path(td)/"ocr.png"
        try:
            prepare_ocr_image(path,prepared)
        except Exception:
            prepared=path
        best=""
        for psm in (6,3):
            try:
                raw=subprocess.check_output(
                    ["tesseract",str(prepared),"stdout","-l",langs,"--oem","1","--psm",str(psm),"--dpi","300"],
                    stderr=subprocess.DEVNULL,text=True,timeout=120
                ).strip()
                if len(raw)>len(best):best=raw
                if len(raw)>=80:break
            except Exception:
                continue
        return best

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
                result=tesseract_text(img)
                if result:texts.append(result)
    elif mime.startswith("image/"):
        result=tesseract_text(path)
        if result:texts.append(result)
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
        category=analysis["category"] if analysis["category"]!="other" else meta["category"]
        suggested_title=analysis["suggested_title"] if analysis["document_type"]!="سند" else meta["suggested_title"]
        confidence=max(analysis["ai_confidence"],meta["confidence"])
        title=row["title"]
        if is_generic_title(title) and suggested_title and confidence>=0.48:
            title=suggested_title
        auto_rename=bool(text and analysis["document_type"]!="سند" and analysis["ai_confidence"]>=0.45 and not row["filename_locked"])
        display_name=analysis["smart_filename"] if auto_rename else row["original_name"]
        detected=json.loads(analysis["extracted_entities"] or "{}")
        entity_id=row["entity_id"]
        if not entity_id and detected.get("person_name"):
            entity_id=upsert_entity(detected["person_name"],"person",analysis.get("country", ""))
        elif not entity_id and detected.get("issuer"):
            entity_id=upsert_entity(detected["issuer"],"organization",analysis.get("country", ""))
        status="done" if text else "empty"
        with db() as con:
            con.execute("""UPDATE documents SET 
title=?,
original_name=?,
ocr_text=?,
ocr_status=?,
category=?,
suggested_title=?,
suggestion_conf=?,
smart_filename=?,
description_fa=?,
description_de=?,
document_type=?,
entity_id=?,
country=?,
ai_confidence=?,
extracted_entities=?,
updated_at=?
WHERE id=?""",
                        (
                        title,
                        display_name,
                        text,
                        status,
                        category,
                        suggested_title,
                        confidence,
                        analysis["smart_filename"],
                        analysis["description_fa"],
                        analysis["description_de"],
                        analysis["document_type"],
                        entity_id,
                        analysis.get("country", ""),
                        analysis["ai_confidence"],
                        analysis["extracted_entities"],
                        now(),
                        row["id"]
                        ))
            fresh=con.execute("SELECT * FROM documents WHERE id=?",(row["id"],)).fetchone()
            fts_upsert(con,fresh)
        if auto_rename and display_name!=row["original_name"]:
            audit("document_auto_renamed",row["id"],"ocr",f'{row["original_name"]} -> {display_name}')
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
    personal_v2_start()
    personal_start()
    th=threading.Thread(target=worker,daemon=True,name="archive-ocr")
    th.start()
    yield
    personal_stop()
    STOP.set()

app=FastAPI(title="Hossein Archive",version="5.0",lifespan=lifespan)

WORK_AGENT_URL=os.getenv("WORK_AGENT_URL","").strip().rstrip("/")
WORK_AGENT_TOKEN=os.getenv("WORK_AGENT_TOKEN","").strip()
WORK_ALLOWED_TASKS={x.strip() for x in os.getenv("WORK_ALLOWED_TASKS","status,docker_status,docker_logs,disk_check,health,backup,fortigate_status,network_snapshot,fortigate_report,fortigate_backup,fortigate_diff,fortigate_rollback,fortigate_change").split(",") if x.strip()}

def _work_device(row):
    if not row:return None
    d=dict(row)
    try:d["details"]=json.loads(d.get("details") or "{}")
    except Exception:d["details"]={}
    d["tags"]=[x for x in (d.get("tags") or "").split(",") if x]
    d["enabled"]=bool(d.get("enabled"))
    return d

def _work_probe(device):
    address=str(device.get("address") or "").strip(); protocol=str(device.get("protocol") or "tcp").lower().strip(); port=int(device.get("port") or 0)
    if not address:return {"status":"error","message":"آدرس دستگاه وارد نشده"}
    started=time.monotonic()
    try:
        if protocol in ("http","https"):
            url=address if address.startswith(("http://","https://")) else f"{protocol}://{address}{(':'+str(port)) if port else ''}"
            req=URLRequest(url,headers={"User-Agent":"HosseinHub-WorkMonitor/1.0"},method="GET")
            with urlopen(req,timeout=5) as resp: code=int(getattr(resp,"status",200))
            status="up" if 200<=code<500 else "down"; message=f"HTTP {code}"
        elif protocol=="icmp":
            proc=subprocess.run(["ping","-c","1","-W","2",address],capture_output=True,text=True,timeout=4)
            status="up" if proc.returncode==0 else "down"; message="ICMP پاسخ داد" if status=="up" else "ICMP بدون پاسخ"
        else:
            if not port:return {"status":"error","message":"برای TCP پورت لازم است"}
            with socket.create_connection((address,port),timeout=4):pass
            status="up"; message=f"TCP/{port} باز است"
        return {"status":status,"message":message,"latency_ms":round((time.monotonic()-started)*1000,1)}
    except Exception as exc:
        return {"status":"down","message":str(exc)[:240],"latency_ms":round((time.monotonic()-started)*1000,1)}

def _work_agent(task,parameters=None):
    if not WORK_AGENT_URL or not WORK_AGENT_TOKEN:return {"ok":False,"error":"WORK_AGENT_URL و WORK_AGENT_TOKEN تنظیم نشده‌اند"}
    if task not in WORK_ALLOWED_TASKS:return {"ok":False,"error":"این عملیات در فهرست مجاز نیست"}
    try:
        req=URLRequest(WORK_AGENT_URL,headers={"Content-Type":"application/json","X-Agent-Token":WORK_AGENT_TOKEN},data=json.dumps({"task":task,"parameters":parameters or {}}).encode(),method="POST")
        with urlopen(req,timeout=30) as resp:return {"ok":True,"result":json.loads(resp.read().decode("utf-8","replace"))}
    except Exception as exc:return {"ok":False,"error":str(exc)[:300]}

@app.get("/api/work/overview")
def work_overview():
    with db() as con:
        devices=[_work_device(r) for r in con.execute("SELECT * FROM work_devices WHERE enabled=1 ORDER BY site,name")]
        events=[dict(r) for r in con.execute("SELECT * FROM work_events ORDER BY id DESC LIMIT 20")]
        actions=[dict(r) for r in con.execute("SELECT * FROM work_actions ORDER BY created_at DESC LIMIT 10")]
    counts={"total":len(devices),"up":sum(x["last_status"]=="up" for x in devices),"down":sum(x["last_status"]=="down" for x in devices),"unknown":sum(x["last_status"] not in ("up","down") for x in devices)}
    return {"counts":counts,"devices":devices,"events":events,"actions":actions,"agent_configured":bool(WORK_AGENT_URL and WORK_AGENT_TOKEN)}

@app.get("/api/work/devices")
def work_devices():
    with db() as con:return {"items":[_work_device(r) for r in con.execute("SELECT * FROM work_devices ORDER BY site,name")]}

@app.get("/api/work/events")
def work_events(limit:int=50, severity:str=""):
    limit=max(1,min(int(limit or 50),200))
    with db() as con:
        if severity in {"info","warning","error"}:
            rows=con.execute("SELECT * FROM work_events WHERE severity=? ORDER BY id DESC LIMIT ?",(severity,limit)).fetchall()
        else:
            rows=con.execute("SELECT * FROM work_events ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return {"items":[dict(r) for r in rows]}

@app.post("/api/work/devices")
def work_add_device(payload:dict=Body(default={} )):
    name=str(payload.get("name") or "").strip()[:120]; address=str(payload.get("address") or "").strip()[:255]
    if not name or not address:raise HTTPException(400,"نام و آدرس دستگاه لازم است")
    protocol=str(payload.get("protocol") or "tcp").lower()
    if protocol not in {"tcp","icmp","http","https"}:raise HTTPException(400,"پروتکل پشتیبانی نمی‌شود")
    did=uuid.uuid4().hex
    with db() as con:
        con.execute("INSERT INTO work_devices(id,name,kind,site,address,port,protocol,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(did,name,str(payload.get("kind") or "server"),str(payload.get("site") or "Tehran"),address,int(payload.get("port") or 0),protocol,str(payload.get("tags") or ""),now(),now()))
        row=con.execute("SELECT * FROM work_devices WHERE id=?",(did,)).fetchone()
    return {"device":_work_device(row)}

@app.post("/api/work/bootstrap")
def work_bootstrap():
    """Add the known Hossein Hub infrastructure as editable inventory records.
    Nothing is probed automatically; the operator explicitly starts checks."""
    assets=[
        ("DC-SRV","domain-controller","Tehran","192.168.1.1",0,"icmp","AD,DNS,DHCP"),
        ("ADC-SRV","domain-controller","Tehran","192.168.1.2",0,"icmp","AD,DNS"),
        ("FortiGate 70G","firewall","Tehran","192.168.1.10",443,"tcp","firewall,wan,vpn"),
        ("WSUS-SRV","server","Tehran","192.168.1.24",8531,"tcp","windows,updates"),
        ("MeshCentral","service","Tehran","192.168.1.30",443,"tcp","remote-access"),
        ("Panasonic KX-TDE200","pbx","Tehran","192.168.1.223",80,"tcp","voip,pbx"),
    ]
    added=0
    with db() as con:
        for name,kind,site,address,port,protocol,tags in assets:
            exists=con.execute("SELECT id FROM work_devices WHERE address=?",(address,)).fetchone()
            if exists:continue
            con.execute("INSERT INTO work_devices(id,name,kind,site,address,port,protocol,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,name,kind,site,address,port,protocol,tags,now(),now()))
            added+=1
    return {"added":added,"total":len(assets),"message":"دارایی‌های شناخته‌شده اضافه شدند؛ بررسی فقط با فرمان شما انجام می‌شود."}

@app.patch("/api/work/devices/{device_id}")
def work_update_device(device_id:str,payload:dict=Body(default={} )):
    allowed={"name","kind","site","address","port","protocol","tags","enabled"}
    updates={k:payload[k] for k in allowed if k in payload}
    if "name" in updates and not str(updates["name"]).strip():raise HTTPException(400,"نام لازم است")
    if "address" in updates and not str(updates["address"]).strip():raise HTTPException(400,"آدرس لازم است")
    if "protocol" in updates and updates["protocol"] not in {"tcp","icmp","http","https"}:raise HTTPException(400,"پروتکل پشتیبانی نمی‌شود")
    if not updates:raise HTTPException(400,"تغییری ارسال نشده است")
    updates["updated_at"]=now()
    with db() as con:
        if not con.execute("SELECT 1 FROM work_devices WHERE id=?",(device_id,)).fetchone():raise HTTPException(404,"دستگاه پیدا نشد")
        fields=", ".join(f"{k}=?" for k in updates)
        con.execute(f"UPDATE work_devices SET {fields} WHERE id=?",(*updates.values(),device_id))
        row=con.execute("SELECT * FROM work_devices WHERE id=?",(device_id,)).fetchone()
    return {"device":_work_device(row)}

@app.delete("/api/work/devices/{device_id}")
def work_delete_device(device_id:str):
    with db() as con:
        if not con.execute("SELECT 1 FROM work_devices WHERE id=?",(device_id,)).fetchone():raise HTTPException(404,"دستگاه پیدا نشد")
        con.execute("DELETE FROM work_devices WHERE id=?",(device_id,))
        con.execute("UPDATE work_actions SET device_id='' WHERE device_id=?",(device_id,))
    return {"ok":True}

@app.post("/api/work/discover")
def work_discover(payload:dict=Body(default={} )):
    """Discover responsive hosts on an explicitly supplied private /24 or smaller network."""
    cidr=str(payload.get("cidr") or "").strip()
    port=int(payload.get("port") or 0)
    try:network=ipaddress.ip_network(cidr,strict=False)
    except ValueError:raise HTTPException(400,"شبکه را به شکل CIDR مثل 192.168.1.0/24 وارد کنید")
    if not network.is_private or network.prefixlen<24:raise HTTPException(400,"برای ایمنی فقط شبکهٔ خصوصی با اندازهٔ /24 یا کوچک‌تر مجاز است")
    hosts=list(network.hosts())
    if len(hosts)>254:raise HTTPException(400,"تعداد میزبان‌ها بیش از حد مجاز است")
    def probe(ip):
        started=time.monotonic()
        try:
            if port:
                with socket.create_connection((str(ip),port),timeout=.7):pass
                return {"address":str(ip),"status":"up","port":port,"latency_ms":round((time.monotonic()-started)*1000,1)}
            proc=subprocess.run(["ping","-c","1","-W","1",str(ip)],capture_output=True,timeout=1.5)
            return {"address":str(ip),"status":"up" if proc.returncode==0 else "down","latency_ms":round((time.monotonic()-started)*1000,1)}
        except Exception:return {"address":str(ip),"status":"down"}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=32) as pool:results=list(pool.map(probe,hosts))
    return {"cidr":str(network),"port":port,"found":[x for x in results if x["status"]=="up"],"scanned":len(hosts)}

@app.post("/api/work/devices/{device_id}/check")
def work_check_device(device_id:str):
    with db() as con:
        row=con.execute("SELECT * FROM work_devices WHERE id=?",(device_id,)).fetchone()
        if not row:raise HTTPException(404,"دستگاه پیدا نشد")
        result=_work_probe(dict(row)); detail=json.dumps(result,ensure_ascii=False)
        con.execute("UPDATE work_devices SET last_status=?,last_checked_at=?,latency_ms=?,details=?,updated_at=? WHERE id=?",(result["status"],now(),result.get("latency_ms"),detail,now(),device_id))
        con.execute("INSERT INTO work_events(device_id,kind,severity,message,details,created_at) VALUES(?,?,?,?,?,?)",(device_id,"probe","error" if result["status"]=="down" else "info",result.get("message",""),detail,now()))
        fresh=con.execute("SELECT * FROM work_devices WHERE id=?",(device_id,)).fetchone()
    return {"device":_work_device(fresh),"result":result}

@app.post("/api/work/actions")
def work_create_action(payload:dict=Body(default={} )):
    task=str(payload.get("task") or "").strip()
    if task not in WORK_ALLOWED_TASKS:raise HTTPException(400,"این عملیات در فهرست مجاز نیست")
    parameters=payload.get("parameters") or {}
    if not isinstance(parameters,dict):raise HTTPException(400,"پارامترهای عملیات نامعتبر است")
    aid=uuid.uuid4().hex
    with db() as con:con.execute("INSERT INTO work_actions(id,device_id,task,parameters,created_at) VALUES(?,?,?,?,?)",(aid,str(payload.get("device_id") or ""),task,json.dumps(parameters,ensure_ascii=False),now()))
    return {"id":aid,"status":"pending","message":"برای اجرا نیازمند تأیید است"}

@app.post("/api/work/fortigate/report")
def fortigate_report(payload:dict=Body(default={} )):
    kind=str(payload.get("kind") or "status").strip()
    if kind not in {"status","interfaces","routes","policies","full"}:raise HTTPException(400,"نوع گزارش FortiGate مجاز نیست")
    if "fortigate_report" not in WORK_ALLOWED_TASKS:raise HTTPException(503,"عملیات گزارش FortiGate فعال نشده است")
    aid=uuid.uuid4().hex
    with db() as con:con.execute("INSERT INTO work_actions(id,device_id,task,parameters,created_at) VALUES(?,?,?,?,?)",(aid,"","fortigate_report",json.dumps({"kind":kind},ensure_ascii=False),now()))
    return {"id":aid,"status":"pending","message":"گزارش FortiGate در صف تأیید قرار گرفت"}

@app.post("/api/work/fortigate/change")
def fortigate_change(payload:dict=Body(default={} )):
    operation=str(payload.get("operation") or "").strip()
    allowed={"set_dns","set_hostname","create_address","disable_policy","enable_policy"}
    if operation not in allowed:raise HTTPException(400,"این تغییر FortiGate در فهرست مجاز نیست")
    aid=uuid.uuid4().hex
    parameters={"operation":operation,"values":payload.get("values") or {}}
    with db() as con:con.execute("INSERT INTO work_actions(id,device_id,task,parameters,created_at) VALUES(?,?,?,?,?)",(aid,"","fortigate_change",json.dumps(parameters,ensure_ascii=False),now()))
    return {"id":aid,"status":"pending","message":"تغییر FortiGate فقط پس از تأیید اجرا می‌شود"}

@app.post("/api/work/actions/{action_id}/approve")
def work_approve_action(action_id:str):
    with db() as con:
        row=con.execute("SELECT * FROM work_actions WHERE id=?",(action_id,)).fetchone()
        if not row:raise HTTPException(404,"درخواست پیدا نشد")
        if row["status"]!="pending":raise HTTPException(409,"این درخواست قبلاً پردازش شده")
        try:parameters=json.loads(row["parameters"] or "{}")
        except Exception:parameters={}
        result=_work_agent(row["task"],parameters); status="done" if result.get("ok") else "failed"
        con.execute("UPDATE work_actions SET status=?,approved_at=?,completed_at=?,result=? WHERE id=?",(status,now(),now(),json.dumps(result,ensure_ascii=False),action_id))
    return {"id":action_id,"status":status,"result":result}

@app.get("/health")
def health():
    with db() as con:
        con.execute("SELECT 1").fetchone()
    return {"status":"ok","app":"hossein-archive","version":"5.0","storage":"local","storage_path":str(ROOT)}

@app.get("/",response_class=HTMLResponse)
def home():
    home_file=WEB/"home.html"
    if home_file.is_file():
        return home_file.read_text(encoding="utf-8")
    # Keep the root usable during an incomplete image copy; never expose a 500 page.
    return HTMLResponse("""<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>
    <title>دستیار من</title><style>body{font-family:Tahoma;max-width:760px;margin:12vh auto;padding:24px;background:#f4f6fb;color:#172039}a{display:inline-block;margin:8px;padding:16px 24px;border-radius:14px;background:#536cf7;color:white;text-decoration:none}</style>
    <h1>دستیار من</h1><p>مرکز برنامه‌ها</p><a href='/personal'>دستیار شخصی</a><a href='/archive'>آرشیو</a><a href='/work'>دستیار کاری</a></html>""")

DRIVE_REMOTE=os.getenv("DRIVE_REMOTE","hossein-drive").strip()
DRIVE_ROOT_FOLDER_ID=os.getenv("DRIVE_ROOT_FOLDER_ID","1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP").strip()
RCLONE_CONFIG_FILE=os.getenv("RCLONE_CONFIG_FILE","/run/secrets/rclone/rclone.conf").strip()
RCLONE_CONFIG_PASS=os.getenv("RCLONE_CONFIG_PASS","").strip()

def _rclone_env():
    env=os.environ.copy()
    if RCLONE_CONFIG_PASS:
        env["RCLONE_CONFIG_PASS"]=RCLONE_CONFIG_PASS
    return env

def _rclone_base():
    if not shutil.which("rclone"):
        raise HTTPException(503,"rclone روی سرور نصب نیست")
    if not RCLONE_CONFIG_FILE or not Path(RCLONE_CONFIG_FILE).is_file():
        raise HTTPException(503,f"فایل تنظیمات Google Drive پیدا نشد: {RCLONE_CONFIG_FILE}")
    return ["rclone","--config",RCLONE_CONFIG_FILE]

def _rclone_run(args,timeout=90):
    try:
        p=subprocess.run(_rclone_base()+args,env=_rclone_env(),text=True,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(504,"پاسخ Google Drive طول کشید")
    if p.returncode:
        detail=(p.stderr or p.stdout or "خطای اتصال Google Drive").strip()[-500:]
        raise HTTPException(502,detail)
    return p

def _rclone_json(args):
    p=_rclone_run(args,90)
    try:
        return json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        raise HTTPException(502,"پاسخ Google Drive قابل خواندن نیست")

def _drive_status():
    try:
        p=_rclone_run(["listremotes"],30)
        remotes={x.strip().rstrip(":") for x in (p.stdout or "").splitlines() if x.strip()}
        if DRIVE_REMOTE not in remotes:
            return {"ok":False,"connected":False,"remote":DRIVE_REMOTE,"detail":f"remote با نام {DRIVE_REMOTE} در rclone تعریف نشده است"}
        _rclone_run(["about",f"{DRIVE_REMOTE}:"],45)
        return {"ok":True,"connected":True,"remote":DRIVE_REMOTE,"root_folder_id":DRIVE_ROOT_FOLDER_ID}
    except HTTPException as exc:
        return {"ok":False,"connected":False,"remote":DRIVE_REMOTE,"detail":str(exc.detail)}

def _drive_items(folder_id):
    root=folder_id or DRIVE_ROOT_FOLDER_ID
    args=["lsjson",f"{DRIVE_REMOTE}:", "--recursive=false","--metadata","--drive-root-folder-id",root]
    rows=_rclone_json(args)
    items=[]
    for row in rows:
        rid=str(row.get("ID") or row.get("id") or "")
        name=str(row.get("Name") or row.get("Path") or "")
        if not name: continue
        isdir=bool(row.get("IsDir"))
        items.append({"id":rid,"name":name,"mimeType":"application/vnd.google-apps.folder" if isdir else (row.get("MimeType") or "application/octet-stream"),"size":row.get("Size",0),"modifiedTime":row.get("ModTime","")})
    items.sort(key=lambda x:(x["mimeType"]!="application/vnd.google-apps.folder",x["name"].lower()))
    return {"ok":True,"path":"Google Drive","items":items}

def _drive_copyid(file_id,target):
    target.mkdir(parents=True,exist_ok=True)
    _rclone_run(["copyid",f"{DRIVE_REMOTE}:",file_id,str(target),"--drive-root-folder-id",DRIVE_ROOT_FOLDER_ID,"--metadata"],180)
    files=[x for x in target.iterdir() if x.is_file()]
    if not files: raise HTTPException(404,"فایل Google Drive پیدا نشد")
    return files[0]

@app.get("/drive",response_class=HTMLResponse)
@app.get("/drive/",response_class=HTMLResponse)
def drive_browser():
    return (WEB/"drive.html").read_text(encoding="utf-8")

@app.get("/api/drive/status")
def drive_status():
    return _drive_status()

@app.get("/api/drive/browse")
def drive_browse(folder_id:str=""):
    status=_drive_status()
    if not status.get("connected"):
        raise HTTPException(503,status.get("detail") or "اتصال Google Drive روی سرور آماده نیست")
    return _drive_items(folder_id)

@app.post("/api/drive/import")
def drive_import(payload:dict=Body(default={})):
    file_id=str(payload.get("file_id") or "").strip()
    if not file_id: raise HTTPException(400,"شناسهٔ فایل لازم است")
    with tempfile.TemporaryDirectory(dir=str(TMP)) as td:
        path=_drive_copyid(file_id,Path(td))
        upload=type("DriveUpload",(),{})()
        upload.filename=path.name; upload.file=path.open("rb")
        try: result=ingest_upload(upload,"google-drive")
        finally: upload.file.close()
    return result

@app.get("/archive",response_class=HTMLResponse)
@app.get("/archive/",response_class=HTMLResponse)
def archive_home():
    # Canonical document archive route; keep /telegram only as a legacy alias.
    return (WEB/"index.html").read_text(encoding="utf-8")

@app.get("/telegram",response_class=HTMLResponse)
@app.get("/telegram/",response_class=HTMLResponse)
def telegram_mini_app():
    # Compatibility URL: the document archive now has one canonical UI.
    return (WEB/"index.html").read_text(encoding="utf-8")

@app.get("/personal",response_class=HTMLResponse)
@app.get("/personal/",response_class=HTMLResponse)
def personal_assistant():
    return (WEB/"personal.html").read_text(encoding="utf-8")

@app.get("/work",response_class=HTMLResponse)
@app.get("/work/",response_class=HTMLResponse)
def work_assistant():
    return (WEB/"work.html").read_text(encoding="utf-8")

PERSONAL_STATUSES={"inbox","today","scheduled","waiting","done","archived"}
PERSONAL_TYPES={"task","reminder","payment","trip","note","email","document","call","appointment"}
PERSONAL_CASE_STATUSES={"active","paused","done","archived"}
CAPTURE_STATUSES={"captured","reviewed","confirmed","archived"}
FACT_TYPES={"person","contact","account","document","preference","reference","decision","note"}
FACT_STATUSES={"active","superseded","archived"}
PERSONAL_TIMEZONE=timezone(timedelta(hours=3,minutes=30))

def _personal_today():
    return datetime.now(PERSONAL_TIMEZONE).date()

def _clean_personal_text(value,limit=4000):
    return str(value or "").strip()[:limit]

def _clean_personal_datetime(value):
    value=_clean_personal_text(value,40)
    if not value:return ""
    try:
        datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise HTTPException(400,"Invalid date or time")
    return value

def _personal_item(row):
    item=dict(row)
    try:item["metadata"]=json.loads(item.get("metadata") or "{}")
    except Exception:item["metadata"]={}
    today=_personal_today().isoformat()
    due=(item.get("due_at") or "")[:10]
    item["is_overdue"]=bool(due and due<today and item["status"] not in ("done","archived"))
    item["is_due_today"]=bool(due==today and item["status"] not in ("done","archived"))
    return item

def _get_personal_item(con,item_id):
    row=con.execute("""SELECT i.*,coalesce(c.title,'') AS case_title,coalesce(c.color,'') AS case_color
        FROM personal_items i LEFT JOIN personal_cases c ON c.id=i.case_id WHERE i.id=?""",(item_id,)).fetchone()
    if not row:raise HTTPException(404,"Personal item not found")
    return row

def _validate_personal_case(con,case_id):
    if case_id and not con.execute("SELECT 1 FROM personal_cases WHERE id=?",(case_id,)).fetchone():
        raise HTTPException(400,"Unknown personal case")

def _capture_suggestion(text):
    first=next((x.strip() for x in text.splitlines() if x.strip()),text).strip()[:240]
    low=text.casefold()
    if any(x in low for x in ("پرداخت","مهلت","قرار","تماس","جواب","پیگیری","یادآوری","ایمیل")):
        return "task",first,{"item_type":"task","status":"inbox"}
    if any(x in low for x in ("هستم","است","شماره","آدرس","حساب","ترجیح","تصمیم")):
        return "fact",first,{"fact_type":"reference"}
    return "note",first,{"item_type":"note","status":"inbox"}

def _project_guess(con,text):
    words=set(re.findall(r"[\w\u0600-\u06ff-]+",text.casefold()))
    best=("",0)
    for row in con.execute("SELECT id,title,aliases FROM personal_projects WHERE status='active'"):
        terms=re.findall(r"[\w\u0600-\u06ff-]+",(row['title']+' '+row['aliases']).casefold())
        score=sum(1 for term in terms if len(term)>1 and term in words)
        if score>best[1]: best=(row['id'],score)
    return (best[0],min(95,55+best[1]*15)) if best[1] else ("",0)

@app.get('/api/personal/projects')
def personal_projects(status:str='active'):
    if status not in ('active','archived','all'): raise HTTPException(400,'Unknown project status')
    with db() as con:
        sql='SELECT * FROM personal_projects'+('' if status=='all' else ' WHERE status=?')+' ORDER BY updated_at DESC'
        rows=list(con.execute(sql,() if status=='all' else (status,)))
    return {'items':[dict(x) for x in rows]}

@app.post('/api/personal/projects')
def create_personal_project(payload:dict=Body(...)):
    title=_clean_personal_text(payload.get('title'),160)
    if not title: raise HTTPException(400,'Project title is required')
    item={'id':str(uuid.uuid4()),'title':title,'aliases':_clean_personal_text(payload.get('aliases'),600),'notes':_clean_personal_text(payload.get('notes'),2000),'status':'active','created_at':now(),'updated_at':now()}
    with db() as con:
        try:
            con.execute('INSERT INTO personal_projects(id,title,aliases,notes,status,created_at,updated_at) VALUES(:id,:title,:aliases,:notes,:status,:created_at,:updated_at)',item)
            con.execute('UPDATE personal_projects SET goal=?,next_action=?,due_date=?,color=?,priority=? WHERE id=?',(_clean_personal_text(payload.get('goal'),1000),_clean_personal_text(payload.get('next_action'),500),_clean_personal_datetime(payload.get('due_date'))[:10],_clean_personal_text(payload.get('color') or '#5b6ff7',20),max(1,min(int(payload.get('priority',2) or 2),3)),item['id']))
        except sqlite3.IntegrityError: raise HTTPException(409,'This project already exists')
        item=dict(con.execute('SELECT * FROM personal_projects WHERE id=?',(item['id'],)).fetchone())
    return {'ok':True,'item':item}

@app.patch('/api/personal/projects/{project_id}')
def update_personal_project(project_id:str,payload:dict=Body(...)):
    with db() as con:
        row=con.execute('SELECT * FROM personal_projects WHERE id=?',(project_id,)).fetchone()
        if not row: raise HTTPException(404)
        values=dict(row)
        for key,limit in (('title',160),('aliases',600),('notes',2000),('status',20),('goal',1000),('next_action',500),('due_date',40),('color',20)):
            if key in payload: values[key]=_clean_personal_text(payload[key],limit)
        if 'priority' in payload: values['priority']=max(1,min(int(payload.get('priority') or 2),3))
        if values['status'] not in ('active','archived') or not values['title']: raise HTTPException(400,'Invalid project')
        values['updated_at']=now()
        con.execute('UPDATE personal_projects SET title=?,aliases=?,notes=?,status=?,goal=?,next_action=?,due_date=?,color=?,priority=?,updated_at=? WHERE id=?',(values['title'],values['aliases'],values['notes'],values['status'],values.get('goal',''),values.get('next_action',''),values.get('due_date',''),values.get('color','#5b6ff7'),values.get('priority',2),values['updated_at'],project_id))
    return {'ok':True,'item':values}

def _capture_dict(row):
    data=dict(row)
    try:data["suggested_data"]=json.loads(data.get("suggested_data") or "{}")
    except Exception:data["suggested_data"]={}
    return data

def _fact_dict(row):
    return dict(row)

def _fact_fingerprint(fact_type,label,value):
    normalized="|".join(_clean_personal_text(x,500).casefold() for x in (fact_type,label,value))
    return hashlib.sha256(normalized.encode()).hexdigest()

def _ensure_safe_fact(label,value,details=""):
    text=" ".join((label,value,details)).casefold()
    if any(x in text for x in ("password","رمز عبور","رمز یکبار","otp","api key","secret key","توکن")):
        raise HTTPException(400,"رمز و توکن را به Fact اضافه نکن")

def _personal_event(con,subject_type,subject_id,action,details=''):
    con.execute('INSERT INTO personal_events(id,subject_type,subject_id,action,details,created_at) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),subject_type,subject_id,action,_clean_personal_text(details,2000),now()))

def _personal_link(con,source_type,source_id,target_type,target_id,relation='related',confidence=100,source='manual'):
    if target_id: con.execute('INSERT OR IGNORE INTO personal_links(id,source_type,source_id,target_type,target_id,relation,confidence,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),source_type,source_id,target_type,target_id,relation,max(0,min(int(confidence),100)),source,now()))

@app.post('/api/personal/links')
def create_personal_link(payload:dict=Body(...)):
    source_type=_clean_personal_text(payload.get('source_type'),40);source_id=_clean_personal_text(payload.get('source_id'),80)
    target_type=_clean_personal_text(payload.get('target_type'),40);target_id=_clean_personal_text(payload.get('target_id'),80)
    if not all((source_type,source_id,target_type,target_id)): raise HTTPException(400,'Link endpoints are required')
    with db() as con:_personal_link(con,source_type,source_id,target_type,target_id,_clean_personal_text(payload.get('relation') or 'related',40),payload.get('confidence',100),'manual')
    return {'ok':True}

@app.get('/api/personal/projects/{project_id}/overview')
def personal_project_overview(project_id:str):
    with db() as con:
        project=con.execute('SELECT * FROM personal_projects WHERE id=?',(project_id,)).fetchone()
        if not project: raise HTTPException(404)
        captures=[_capture_dict(x) for x in con.execute("SELECT * FROM personal_captures WHERE project_id=? AND status='captured' ORDER BY created_at DESC",(project_id,))]
        facts=[_fact_dict(x) for x in con.execute("SELECT * FROM personal_facts WHERE project_id=? AND status='active' ORDER BY updated_at DESC",(project_id,))]
        items=[dict(x) for x in con.execute("SELECT * FROM personal_items WHERE project_id=? AND status NOT IN ('done','archived') ORDER BY due_at,updated_at DESC",(project_id,))]
        commitments=[dict(x) for x in con.execute("SELECT * FROM personal_commitments WHERE project_id=? ORDER BY updated_at DESC",(project_id,))]
        decisions=[dict(x) for x in con.execute("SELECT * FROM personal_decisions WHERE project_id=? ORDER BY updated_at DESC",(project_id,))]
        calendar=[dict(x) for x in con.execute("SELECT * FROM personal_calendar WHERE project_id=? ORDER BY starts_at",(project_id,))]
        events=[dict(x) for x in con.execute('SELECT * FROM personal_events WHERE subject_type=? AND subject_id=? ORDER BY created_at DESC LIMIT 100',('project',project_id))]
    return {'project':dict(project),'captures':captures,'facts':facts,'items':items,'commitments':commitments,'decisions':decisions,'calendar':calendar,'events':events}

@app.get("/api/personal/dashboard")
def personal_dashboard():
    local_date=_personal_today()
    today=local_date.isoformat()
    tomorrow=(local_date+timedelta(days=1)).isoformat()
    next_week=(local_date+timedelta(days=7)).isoformat()
    base="status NOT IN ('done','archived')"
    select="""SELECT i.*,coalesce(c.title,'') AS case_title,coalesce(c.color,'') AS case_color
        FROM personal_items i LEFT JOIN personal_cases c ON c.id=i.case_id"""
    with db() as con:
        counts={
            "inbox":con.execute("SELECT count(*) FROM personal_items WHERE status='inbox'").fetchone()[0],
            "today":con.execute("SELECT count(*) FROM personal_items WHERE status='today' OR (due_at<>'' AND substr(due_at,1,10)=? AND "+base+")",(today,)).fetchone()[0],
            "overdue":con.execute("SELECT count(*) FROM personal_items WHERE due_at<>'' AND substr(due_at,1,10)<? AND "+base,(today,)).fetchone()[0],
            "waiting":con.execute("SELECT count(*) FROM personal_items WHERE status='waiting'").fetchone()[0],
            "done":con.execute("SELECT count(*) FROM personal_items WHERE status='done' AND substr(completed_at,1,10)=?",(today,)).fetchone()[0],
            "active_cases":con.execute("SELECT count(*) FROM personal_cases WHERE status='active'").fetchone()[0],
        }
        focus=list(con.execute(select+" WHERE i.status NOT IN ('done','archived') AND (i.status='today' OR (i.due_at<>'' AND substr(i.due_at,1,10)<=?)) ORDER BY CASE WHEN substr(i.due_at,1,10)<? THEN 0 ELSE 1 END,i.priority DESC,i.due_at LIMIT 20",(today,today)))
        waiting=list(con.execute(select+" WHERE i.status='waiting' ORDER BY CASE WHEN i.follow_up_at='' THEN 1 ELSE 0 END,i.follow_up_at LIMIT 12"))
        upcoming=list(con.execute(select+" WHERE i.status NOT IN ('done','archived','today') AND i.due_at<>'' AND substr(i.due_at,1,10)>=? AND substr(i.due_at,1,10)<=? ORDER BY i.due_at LIMIT 12",(tomorrow,next_week)))
        inbox=list(con.execute(select+" WHERE i.status='inbox' ORDER BY i.created_at DESC LIMIT 8"))
    return {"date":today,"counts":counts,"focus":[_personal_item(x) for x in focus],"waiting":[_personal_item(x) for x in waiting],"upcoming":[_personal_item(x) for x in upcoming],"inbox":[_personal_item(x) for x in inbox]}

@app.get("/api/personal/items")
def personal_items(status:str="",item_type:str="",case_id:str="",q:str="",limit:int=200):
    where=["1=1"];args=[]
    if status:
        if status=="open":where.append("i.status NOT IN ('done','archived')")
        elif status=="overdue":
            where.append("i.status NOT IN ('done','archived') AND i.due_at<>'' AND substr(i.due_at,1,10)<?")
            args.append(_personal_today().isoformat())
        elif status in PERSONAL_STATUSES:where.append("i.status=?");args.append(status)
        else:raise HTTPException(400,"Unknown status")
    if item_type:
        if item_type not in PERSONAL_TYPES:raise HTTPException(400,"Unknown item type")
        where.append("i.item_type=?");args.append(item_type)
    if case_id:where.append("i.case_id=?");args.append(case_id)
    if q.strip():
        term=f"%{q.strip()}%";where.append("(i.title LIKE ? OR i.details LIKE ? OR c.title LIKE ?)");args.extend([term,term,term])
    limit=max(1,min(limit,500))
    sql="""SELECT i.*,coalesce(c.title,'') AS case_title,coalesce(c.color,'') AS case_color
        FROM personal_items i LEFT JOIN personal_cases c ON c.id=i.case_id
        WHERE %s ORDER BY CASE i.status WHEN 'today' THEN 0 WHEN 'inbox' THEN 1 WHEN 'waiting' THEN 2 WHEN 'scheduled' THEN 3 WHEN 'done' THEN 4 ELSE 5 END,
        CASE WHEN i.due_at='' THEN 1 ELSE 0 END,i.due_at,i.priority DESC,i.created_at DESC LIMIT ?"""%(" AND ".join(where))
    with db() as con:rows=list(con.execute(sql,[*args,limit]))
    return {"items":[_personal_item(x) for x in rows],"count":len(rows)}

@app.post("/api/personal/items")
def create_personal_item(payload:dict=Body(...)):
    title=_clean_personal_text(payload.get("title"),240)
    if not title:raise HTTPException(400,"Title is required")
    item_type=_clean_personal_text(payload.get("item_type") or "task",30)
    status=_clean_personal_text(payload.get("status") or "inbox",30)
    if item_type not in PERSONAL_TYPES:raise HTTPException(400,"Unknown item type")
    if status not in PERSONAL_STATUSES:raise HTTPException(400,"Unknown status")
    priority=max(1,min(int(payload.get("priority",2) or 2),3))
    due_at=_clean_personal_datetime(payload.get("due_at"))
    follow_up_at=_clean_personal_datetime(payload.get("follow_up_at"))
    case_id=_clean_personal_text(payload.get("case_id"),80)
    amount=payload.get("amount")
    try:amount=float(amount) if amount not in (None,"") else None
    except (TypeError,ValueError):raise HTTPException(400,"Invalid amount")
    project_id=_clean_personal_text(payload.get('project_id'),80);item_id=str(uuid.uuid4());stamp=now()
    with db() as con:
        _validate_personal_case(con,case_id)
        if project_id and not con.execute("SELECT 1 FROM personal_projects WHERE id=?",(project_id,)).fetchone():raise HTTPException(400,'Unknown project')
        con.execute("""INSERT INTO personal_items(id,item_type,title,details,status,priority,due_at,follow_up_at,repeat_rule,case_id,project_id,document_id,source,amount,currency,metadata,completed_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            item_id,item_type,title,_clean_personal_text(payload.get("details")),status,priority,due_at,follow_up_at,
            _clean_personal_text(payload.get("repeat_rule"),100),case_id,project_id,_clean_personal_text(payload.get("document_id"),80),
            _clean_personal_text(payload.get("source") or "manual",50),amount,_clean_personal_text(payload.get("currency"),12),
            json.dumps(payload.get("metadata") if isinstance(payload.get("metadata"),dict) else {},ensure_ascii=False),
            stamp if status=="done" else "",stamp,stamp))
        _personal_event(con,'item',item_id,'created',title)
        if project_id:_personal_link(con,'item',item_id,'project',project_id,'belongs_to')
        row=_get_personal_item(con,item_id)
    return {"ok":True,"item":_personal_item(row)}

@app.post("/api/personal/capture")
def capture_personal_item(payload:dict=Body(...)):
    text=_clean_personal_text(payload.get("text"),4000)
    if not text:raise HTTPException(400,"Text is required")
    normalized=" ".join(text.casefold().split())
    digest=hashlib.sha256(normalized.encode()).hexdigest()
    suggested_type,title,suggested_data=_capture_suggestion(text)
    stamp=now();capture_id=str(uuid.uuid4());requested_project=_clean_personal_text(payload.get('project_id'),80)
    with db() as con:
        existing=con.execute("SELECT * FROM personal_captures WHERE normalized_hash=?",(digest,)).fetchone()
        if existing:return {"ok":True,"duplicate":True,"capture":_capture_dict(existing)}
        if requested_project and not con.execute("SELECT 1 FROM personal_projects WHERE id=? AND status='active'",(requested_project,)).fetchone(): raise HTTPException(400,'Unknown project')
        guessed,confidence=_project_guess(con,text)
        project_id=requested_project or guessed
        con.execute("""INSERT INTO personal_captures(id,raw_text,normalized_hash,source,status,suggested_type,suggested_title,suggested_data,project_id,suggested_project_id,project_confidence,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(capture_id,text,digest,_clean_personal_text(payload.get("source") or "quick_capture",50),"captured",suggested_type,title,json.dumps(suggested_data,ensure_ascii=False),project_id,guessed,confidence,stamp,stamp))
        row=con.execute("SELECT * FROM personal_captures WHERE id=?",(capture_id,)).fetchone()
    personal_v2_analyze(capture_id)
    return {"ok":True,"duplicate":False,"capture":_capture_dict(row)}

@app.get("/api/personal/captures")
def personal_captures(status:str="captured",limit:int=100):
    if status and status not in CAPTURE_STATUSES:raise HTTPException(400,"Unknown capture status")
    limit=max(1,min(limit,500))
    with db() as con:
        sql="SELECT * FROM personal_captures"+(" WHERE status=?" if status else "")+" ORDER BY created_at DESC LIMIT ?"
        rows=list(con.execute(sql,([status] if status else [])+[limit]))
    return {"items":[_capture_dict(x) for x in rows],"count":len(rows)}

@app.post("/api/personal/captures/{capture_id}/confirm")
def confirm_capture(capture_id:str,payload:dict=Body(...)):
    action=_clean_personal_text(payload.get("action"),30)
    if action not in ("task","fact","archive"):raise HTTPException(400,"Choose task, fact, or archive")
    with db() as con:
        capture=con.execute("SELECT * FROM personal_captures WHERE id=?",(capture_id,)).fetchone()
        if not capture:raise HTTPException(404,"Capture not found")
        if capture["status"]=="confirmed":
            return {"ok":True,"duplicate":True,"item_id":capture["confirmed_item_id"],"fact_id":capture["confirmed_fact_id"]}
        if capture["status"]=="archived":raise HTTPException(409,"Capture is archived")
        if action=="archive":
            con.execute("UPDATE personal_captures SET status='archived',updated_at=?,confirmed_at=? WHERE id=?",(now(),now(),capture_id))
            return {"ok":True,"archived":True}
    if action=="task":
        item_payload=dict(payload.get("item") or {})
        item_payload.setdefault("title",capture["suggested_title"] or capture["raw_text"][:240])
        item_payload.setdefault("details",capture["raw_text"])
        item_payload.setdefault("item_type","task")
        item_payload.setdefault("status","inbox")
        item_payload.setdefault("project_id",capture["project_id"])
        item_payload["source"]="capture_confirmed"
        item=create_personal_item(item_payload)["item"]
        with db() as con:
            con.execute("UPDATE personal_captures SET status='confirmed',confirmed_item_id=?,updated_at=?,confirmed_at=? WHERE id=?",(item["id"],now(),now(),capture_id));_personal_link(con,'capture',capture_id,'item',item['id'],'converted_to');_personal_event(con,'capture',capture_id,'confirmed_task',item['title'])
        return {"ok":True,"item":item}
    fact_payload=dict(payload.get("fact") or {})
    fact_payload.setdefault("label",capture["suggested_title"] or capture["raw_text"][:240])
    fact_payload.setdefault("value",capture["raw_text"])
    fact_payload.setdefault("fact_type","reference")
    fact_payload.setdefault("project_id",capture["project_id"])
    fact_payload["source_capture_id"]=capture_id
    result=create_personal_fact(fact_payload)
    with db() as con:
        con.execute("UPDATE personal_captures SET status='confirmed',confirmed_fact_id=?,updated_at=?,confirmed_at=? WHERE id=?",(result["fact"]["id"],now(),now(),capture_id))
    return {"ok":True,**result}

@app.post("/api/personal/captures/{capture_id}/archive")
def archive_capture(capture_id:str):
    with db() as con:
        if not con.execute("SELECT 1 FROM personal_captures WHERE id=?",(capture_id,)).fetchone():raise HTTPException(404)
        con.execute("UPDATE personal_captures SET status='archived',updated_at=? WHERE id=?",(now(),capture_id))
    return {"ok":True}

@app.get("/api/personal/facts")
def personal_facts(status:str="active",fact_type:str="",q:str="",limit:int=200):
    if status and status not in FACT_STATUSES:raise HTTPException(400,"Unknown fact status")
    if fact_type and fact_type not in FACT_TYPES:raise HTTPException(400,"Unknown fact type")
    where=["1=1"];args=[]
    if status:where.append("status=?");args.append(status)
    if fact_type:where.append("fact_type=?");args.append(fact_type)
    if q.strip():
        term=f"%{q.strip()}%";where.append("(label LIKE ? OR value LIKE ? OR details LIKE ?)");args.extend([term,term,term])
    limit=max(1,min(limit,500))
    with db() as con:rows=list(con.execute("SELECT * FROM personal_facts WHERE "+" AND ".join(where)+" ORDER BY updated_at DESC LIMIT ?",[*args,limit]))
    return {"items":[_fact_dict(x) for x in rows],"count":len(rows)}

@app.post("/api/personal/facts")
def create_personal_fact(payload:dict=Body(...)):
    fact_type=_clean_personal_text(payload.get("fact_type") or "reference",40)
    label=_clean_personal_text(payload.get("label"),240);value=_clean_personal_text(payload.get("value"),4000)
    if fact_type not in FACT_TYPES:raise HTTPException(400,"Unknown fact type")
    if not label or not value:raise HTTPException(400,"Fact label and value are required")
    details=_clean_personal_text(payload.get("details"));_ensure_safe_fact(label,value,details)
    case_id=_clean_personal_text(payload.get("case_id"),80);entity_id=_clean_personal_text(payload.get("entity_id"),80);project_id=_clean_personal_text(payload.get('project_id'),80)
    fingerprint=_fact_fingerprint(fact_type,label,value);fact_id=str(uuid.uuid4());stamp=now()
    with db() as con:
        _validate_personal_case(con,case_id)
        if project_id and not con.execute('SELECT 1 FROM personal_projects WHERE id=?',(project_id,)).fetchone():raise HTTPException(400,'Unknown project')
        existing=con.execute("SELECT * FROM personal_facts WHERE fingerprint=?",(fingerprint,)).fetchone()
        if existing:return {"ok":True,"duplicate":True,"fact":_fact_dict(existing)}
        con.execute("""INSERT INTO personal_facts(id,fact_type,label,value,details,status,confidence,case_id,entity_id,project_id,source_capture_id,fingerprint,created_at,updated_at)
            VALUES(?,?,?,?,?,'active','confirmed',?,?,?,?,?,?,?)""",(fact_id,fact_type,label,value,details,case_id,entity_id,project_id,_clean_personal_text(payload.get("source_capture_id"),80),fingerprint,stamp,stamp))
        row=con.execute("SELECT * FROM personal_facts WHERE id=?",(fact_id,)).fetchone()
        con.execute("INSERT INTO personal_fact_events(id,fact_id,action,snapshot,created_at) VALUES(?,?,?,?,?)",(str(uuid.uuid4()),fact_id,"created",json.dumps(dict(row),ensure_ascii=False),stamp))
    return {"ok":True,"duplicate":False,"fact":_fact_dict(row)}

@app.get("/api/personal/facts/{fact_id}")
def personal_fact(fact_id:str):
    with db() as con:
        row=con.execute("SELECT * FROM personal_facts WHERE id=?",(fact_id,)).fetchone()
        if not row:raise HTTPException(404)
        history=[dict(x) for x in con.execute("SELECT action,snapshot,created_at FROM personal_fact_events WHERE fact_id=? ORDER BY created_at DESC",(fact_id,))]
    for event in history:
        try:event["snapshot"]=json.loads(event["snapshot"])
        except Exception:pass
    return {"fact":_fact_dict(row),"history":history}

@app.patch("/api/personal/facts/{fact_id}")
def update_personal_fact(fact_id:str,payload:dict=Body(...)):
    allowed={"fact_type","label","value","details","status","case_id","entity_id","project_id"}
    with db() as con:
        current=con.execute("SELECT * FROM personal_facts WHERE id=?",(fact_id,)).fetchone()
        if not current:raise HTTPException(404)
        values=dict(current)
        for key,value in payload.items():
            if key not in allowed:continue
            if key=="fact_type":
                value=_clean_personal_text(value,40)
                if value not in FACT_TYPES:raise HTTPException(400,"Unknown fact type")
            elif key=="status":
                value=_clean_personal_text(value,30)
                if value not in FACT_STATUSES:raise HTTPException(400,"Unknown fact status")
            elif key in ("label","value","details"):value=_clean_personal_text(value,4000 if key!="label" else 240)
            elif key=="case_id":value=_clean_personal_text(value,80);_validate_personal_case(con,value)
            elif key=="project_id":
                value=_clean_personal_text(value,80)
                if value and not con.execute('SELECT 1 FROM personal_projects WHERE id=?',(value,)).fetchone():raise HTTPException(400,'Unknown project')
            else:value=_clean_personal_text(value,80)
            values[key]=value
        if not values["label"] or not values["value"]:raise HTTPException(400,"Fact label and value are required")
        _ensure_safe_fact(values["label"],values["value"],values["details"])
        new_fingerprint=_fact_fingerprint(values["fact_type"],values["label"],values["value"])
        match=con.execute("SELECT id FROM personal_facts WHERE fingerprint=? AND id<>?",(new_fingerprint,fact_id)).fetchone()
        if match:raise HTTPException(409,"This fact already exists")
        values["fingerprint"]=new_fingerprint;values["updated_at"]=now()
        if values["status"]=="archived" and current["status"]!="archived":values["archived_at"]=now()
        con.execute("""UPDATE personal_facts SET fact_type=?,label=?,value=?,details=?,status=?,case_id=?,entity_id=?,project_id=?,fingerprint=?,updated_at=?,archived_at=? WHERE id=?""",(
            values["fact_type"],values["label"],values["value"],values["details"],values["status"],values["case_id"],values["entity_id"],values.get("project_id",''),values["fingerprint"],values["updated_at"],values["archived_at"],fact_id))
        fresh=con.execute("SELECT * FROM personal_facts WHERE id=?",(fact_id,)).fetchone()
        con.execute("INSERT INTO personal_fact_events(id,fact_id,action,snapshot,created_at) VALUES(?,?,?,?,?)",(str(uuid.uuid4()),fact_id,"updated",json.dumps(dict(fresh),ensure_ascii=False),now()))
    return {"ok":True,"fact":_fact_dict(fresh)}

@app.patch("/api/personal/items/{item_id}")
def update_personal_item(item_id:str,payload:dict=Body(...)):
    allowed={"item_type","title","details","status","priority","due_at","follow_up_at","repeat_rule","case_id","project_id","document_id","source","amount","currency","metadata"}
    updates=[];args=[]
    with db() as con:
        current=_get_personal_item(con,item_id)
        for key,value in payload.items():
            if key not in allowed:continue
            if key=="title":
                value=_clean_personal_text(value,240)
                if not value:raise HTTPException(400,"Title is required")
            elif key in ("details","metadata"):
                value=json.dumps(value,ensure_ascii=False) if key=="metadata" and isinstance(value,dict) else _clean_personal_text(value)
            elif key=="status":
                value=_clean_personal_text(value,30)
                if value not in PERSONAL_STATUSES:raise HTTPException(400,"Unknown status")
            elif key=="item_type":
                value=_clean_personal_text(value,30)
                if value not in PERSONAL_TYPES:raise HTTPException(400,"Unknown item type")
            elif key=="priority":value=max(1,min(int(value or 2),3))
            elif key in ("due_at","follow_up_at"):value=_clean_personal_datetime(value)
            elif key=="case_id":
                value=_clean_personal_text(value,80);_validate_personal_case(con,value)
            elif key=="project_id":
                value=_clean_personal_text(value,80)
                if value and not con.execute('SELECT 1 FROM personal_projects WHERE id=?',(value,)).fetchone():raise HTTPException(400,'Unknown project')
            elif key=="amount":
                try:value=float(value) if value not in (None,"") else None
                except (TypeError,ValueError):raise HTTPException(400,"Invalid amount")
            else:value=_clean_personal_text(value,240)
            updates.append(f"{key}=?");args.append(value)
        if not updates:return {"ok":True,"item":_personal_item(current)}
        if payload.get("status")=="done":updates.append("completed_at=?");args.append(now())
        elif "status" in payload and current["status"]=="done":updates.append("completed_at=?");args.append("")
        updates.append("updated_at=?");args.append(now());args.append(item_id)
        con.execute(f"UPDATE personal_items SET {','.join(updates)} WHERE id=?",args)
        row=_get_personal_item(con,item_id)
    return {"ok":True,"item":_personal_item(row)}

@app.delete("/api/personal/items/{item_id}")
def delete_personal_item(item_id:str):
    with db() as con:
        if not con.execute("SELECT 1 FROM personal_items WHERE id=?",(item_id,)).fetchone():raise HTTPException(404)
        voices=list(con.execute("SELECT id FROM personal_voice WHERE item_id=?",(item_id,)))
        con.execute("DELETE FROM personal_voice WHERE item_id=?",(item_id,))
        con.execute("DELETE FROM personal_items WHERE id=?",(item_id,))
    for voice in voices:
        (ROOT/'personal-private'/'voice'/voice['id']).unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/personal/cases")
def personal_cases(status:str=""):
    where="WHERE c.status=?" if status in PERSONAL_CASE_STATUSES else "";args=[status] if where else []
    with db() as con:
        rows=list(con.execute(f"""SELECT c.*,
            sum(CASE WHEN i.status NOT IN ('done','archived') THEN 1 ELSE 0 END) AS open_items,
            sum(CASE WHEN i.status='done' THEN 1 ELSE 0 END) AS done_items
            FROM personal_cases c LEFT JOIN personal_items i ON i.case_id=c.id {where}
            GROUP BY c.id ORDER BY CASE c.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,c.priority DESC,c.updated_at DESC""",args))
    return {"items":[dict(x) for x in rows],"count":len(rows)}

@app.post("/api/personal/cases")
def create_personal_case(payload:dict=Body(...)):
    title=_clean_personal_text(payload.get("title"),240)
    if not title:raise HTTPException(400,"Title is required")
    status=_clean_personal_text(payload.get("status") or "active",30)
    if status not in PERSONAL_CASE_STATUSES:raise HTTPException(400,"Unknown case status")
    case_id=str(uuid.uuid4());stamp=now()
    with db() as con:
        con.execute("""INSERT INTO personal_cases(id,title,kind,status,priority,color,notes,next_action,due_date,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(case_id,title,_clean_personal_text(payload.get("kind") or "personal",50),status,
            max(1,min(int(payload.get("priority",2) or 2),3)),_clean_personal_text(payload.get("color") or "#5b7cfa",20),
            _clean_personal_text(payload.get("notes")),_clean_personal_text(payload.get("next_action"),500),
            _clean_personal_datetime(payload.get("due_date"))[:10],stamp,stamp))
        row=con.execute("SELECT * FROM personal_cases WHERE id=?",(case_id,)).fetchone()
    return {"ok":True,"item":dict(row)}

@app.patch("/api/personal/cases/{case_id}")
def update_personal_case(case_id:str,payload:dict=Body(...)):
    allowed={"title","kind","status","priority","color","notes","next_action","due_date"};updates=[];args=[]
    with db() as con:
        if not con.execute("SELECT 1 FROM personal_cases WHERE id=?",(case_id,)).fetchone():raise HTTPException(404)
        for key,value in payload.items():
            if key not in allowed:continue
            if key=="title":
                value=_clean_personal_text(value,240)
                if not value:raise HTTPException(400,"Title is required")
            elif key=="status":
                value=_clean_personal_text(value,30)
                if value not in PERSONAL_CASE_STATUSES:raise HTTPException(400,"Unknown case status")
            elif key=="priority":value=max(1,min(int(value or 2),3))
            elif key=="due_date":value=_clean_personal_datetime(value)[:10]
            else:value=_clean_personal_text(value,4000 if key=="notes" else 500)
            updates.append(f"{key}=?");args.append(value)
        if updates:
            updates.append("updated_at=?");args.append(now());args.append(case_id)
            con.execute(f"UPDATE personal_cases SET {','.join(updates)} WHERE id=?",args)
        row=con.execute("SELECT * FROM personal_cases WHERE id=?",(case_id,)).fetchone()
    return {"ok":True,"item":dict(row)}

@app.delete("/api/personal/cases/{case_id}")
def delete_personal_case(case_id:str):
    with db() as con:
        con.execute("UPDATE personal_items SET case_id='',updated_at=? WHERE case_id=?",(now(),case_id))
        changed=con.execute("DELETE FROM personal_cases WHERE id=?",(case_id,)).rowcount
        if not changed:raise HTTPException(404)
    return {"ok":True}

@app.get("/api/personal/search")
def personal_search(q:str=""):
    q=q.strip()
    if len(q)<2:return {"items":[]}
    term=f"%{q}%"
    with db() as con:
        tasks=[dict(x) for x in con.execute("SELECT id,title,details,status,item_type,updated_at FROM personal_items WHERE title LIKE ? OR details LIKE ? ORDER BY updated_at DESC LIMIT 20",(term,term))]
        cases=[dict(x) for x in con.execute("SELECT id,title,notes,status,'case' AS item_type,updated_at FROM personal_cases WHERE title LIKE ? OR notes LIKE ? ORDER BY updated_at DESC LIMIT 10",(term,term))]
        facts=[dict(x) for x in con.execute("SELECT id,label AS title,value||CASE WHEN details<>'' THEN ' · '||details ELSE '' END AS details,status,'fact' AS item_type,updated_at FROM personal_facts WHERE status='active' AND (label LIKE ? OR value LIKE ? OR details LIKE ?) ORDER BY updated_at DESC LIMIT 20",(term,term,term))]
        docs=[dict(x) for x in con.execute("SELECT id,title,original_name AS details,'document' AS status,'document' AS item_type,updated_at FROM documents WHERE deleted=0 AND (title LIKE ? OR original_name LIKE ? OR notes LIKE ?) ORDER BY updated_at DESC LIMIT 20",(term,term,term))]
        captures=[dict(x) for x in con.execute("SELECT id,suggested_title AS title,raw_text AS details,status,'capture' AS item_type,updated_at FROM personal_captures WHERE raw_text LIKE ? ORDER BY updated_at DESC LIMIT 20",(term,))]
        commitments=[dict(x) for x in con.execute("SELECT id,title,details,status,'commitment' AS item_type,updated_at FROM personal_commitments WHERE title LIKE ? OR details LIKE ? ORDER BY updated_at DESC LIMIT 20",(term,term))]
        decisions=[dict(x) for x in con.execute("SELECT id,title,decision AS details,status,'decision' AS item_type,updated_at FROM personal_decisions WHERE title LIKE ? OR decision LIKE ? OR reason LIKE ? ORDER BY updated_at DESC LIMIT 20",(term,term,term))]
        people=[dict(x) for x in con.execute("SELECT id,name AS title,notes AS details,'active' AS status,'person' AS item_type,updated_at FROM entities WHERE kind='person' AND (name LIKE ? OR notes LIKE ?) ORDER BY updated_at DESC LIMIT 20",(term,term))]
    return {"items":[*tasks,*cases,*facts,*captures,*commitments,*decisions,*people,*docs]}

@app.get("/api/home/search")
def home_search(q:str=""):
    """Unified, read-only search used by the home dashboard."""
    q=q.strip()
    if len(q)<2:return {"items":[]}
    term=f"%{q}%"
    with db() as con:
        rows=[]
        rows += [dict(x) for x in con.execute("SELECT id,title,details,status,'task' AS item_type,updated_at FROM personal_items WHERE title LIKE ? OR details LIKE ? ORDER BY updated_at DESC LIMIT 12",(term,term))]
        rows += [dict(x) for x in con.execute("SELECT id,title,notes AS details,status,'project' AS item_type,updated_at FROM personal_projects WHERE title LIKE ? OR aliases LIKE ? OR notes LIKE ? ORDER BY updated_at DESC LIMIT 10",(term,term,term))]
        rows += [dict(x) for x in con.execute("SELECT id,label AS title,value||CASE WHEN details<>'' THEN ' · '||details ELSE '' END AS details,status,'fact' AS item_type,updated_at FROM personal_facts WHERE status='active' AND (label LIKE ? OR value LIKE ? OR details LIKE ?) ORDER BY updated_at DESC LIMIT 12",(term,term,term))]
        rows += [dict(x) for x in con.execute("SELECT id,suggested_title AS title,raw_text AS details,status,'capture' AS item_type,updated_at FROM personal_captures WHERE raw_text LIKE ? OR suggested_title LIKE ? ORDER BY updated_at DESC LIMIT 12",(term,term))]
        rows += [dict(x) for x in con.execute("SELECT id,title,original_name AS details,'active' AS status,'document' AS item_type,updated_at FROM documents WHERE deleted=0 AND (title LIKE ? OR original_name LIKE ? OR notes LIKE ?) ORDER BY updated_at DESC LIMIT 12",(term,term,term))]
        rows += [dict(x) for x in con.execute("SELECT id,title,details,status,'email' AS item_type,updated_at FROM personal_items WHERE item_type='email' AND (title LIKE ? OR details LIKE ?) ORDER BY updated_at DESC LIMIT 12",(term,term))]
    return {"items":rows[:50]}

@app.get("/api/stats")
def stats():
    today=datetime.now(timezone.utc).date().isoformat()
    warning=(datetime.now(timezone.utc).date()+timedelta(days=60)).isoformat()
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
            "expired":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND expiry_date<>'' AND expiry_date<?",(today,)).fetchone()[0],
            "expiring":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND expiry_date>=? AND expiry_date<=?",(today,warning)).fetchone()[0],
            "missing":con.execute("""SELECT count(*) FROM entity_requirements r WHERE NOT EXISTS(
                SELECT 1 FROM documents d WHERE d.deleted=0 AND d.entity_id=r.entity_id
                AND d.document_type=r.document_type AND (r.country='' OR d.country=r.country)
            )""").fetchone()[0],
        }

@app.get("/api/documents")
def documents(q:str="",category:str="",source:str="",ocr:str="",days:int=0,scope:str="all",sort:str="newest",entity_id:str="",document_type:str="",country:str="",validity:str=""):
    where=["1=1"];args=[]
    where.append("deleted=?");args.append(1 if scope=="trash" else 0)
    if scope=="favorites":where.append("favorite=1")
    if scope=="uncategorized":where.append("category='other'")
    if category:
        where.append("category=?");args.append(category)
    if entity_id:
        where.append("entity_id=?");args.append(entity_id)
    if document_type:
        where.append("document_type=?");args.append(document_type)
    if country:
        where.append("country=?");args.append(country)
    today=datetime.now(timezone.utc).date().isoformat()
    warning=(datetime.now(timezone.utc).date()+timedelta(days=60)).isoformat()
    if validity=="expired":
        where.append("expiry_date<>'' AND expiry_date<?");args.append(today)
    elif validity=="expiring":
        where.append("expiry_date>=? AND expiry_date<=?");args.extend([today,warning])
    elif validity=="valid":
        where.append("(expiry_date='' OR expiry_date>?)");args.append(warning)
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
            where.append("(title LIKE ? OR original_name LIKE ? OR ocr_text LIKE ? OR tags LIKE ? OR notes LIKE ? OR entity_id IN (SELECT id FROM entities WHERE name LIKE ?))")
            args.extend([x,x,x,x,x,x])
    order={"newest":"created_at DESC","oldest":"created_at ASC","name":"title COLLATE NOCASE ASC","size":"size DESC"}.get(sort,"created_at DESC")
    sql=f"""SELECT id,title,original_name,mime,media_kind,size,ocr_status,transcript_status,category,tags,suggested_title,suggestion_conf,favorite,deleted,source,created_at,updated_at,ocr_text,smart_filename,document_type,country,entity_id,issue_date,expiry_date,version_no,project_id,action_status,follow_up_at,
            coalesce((SELECT name FROM entities e WHERE e.id=documents.entity_id),'') AS entity_name
            FROM documents WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 500"""
    with db() as con:
        rows=[]
        for r in con.execute(sql,args):
            d=dict(r)
            d["snippet"]=make_snippet(d.pop("ocr_text",""),q) if q.strip() else ""
            d["has_preview"]=(PREV/f'{d["id"]}.jpg').exists()
            d["validity_status"]=document_validity(d.get("expiry_date"))
            rows.append(d)
    return {"items":rows,"count":len(rows)}

@app.get("/api/documents/{did}")
def document(did:str):
    with db() as con:
        row=con.execute("""SELECT d.*,
            coalesce((SELECT name FROM entities e WHERE e.id=d.entity_id),'') AS entity_name
            FROM documents d WHERE d.id=?""",(did,)).fetchone()
        if not row:raise HTTPException(404)
        d=dict(row);d["ocr_text"]=(d["ocr_text"] or "")[:30000]
        d["validity_status"]=document_validity(d.get("expiry_date"))
        return d

@app.get("/api/media")
def media_assets(kind:str="",q:str="",limit:int=100):
    """Unified media view for documents, images, audio and video."""
    allowed={"document","image","audio","video","file"}
    if kind and kind not in allowed: raise HTTPException(400,"Unknown media kind")
    where=["deleted=0"];args=[]
    if kind: where.append("media_kind=?");args.append(kind)
    if q.strip():
        term=f"%{q.strip()}%";where.append("(title LIKE ? OR original_name LIKE ? OR tags LIKE ? OR notes LIKE ? OR ocr_text LIKE ? OR transcript LIKE ?)");args.extend([term]*6)
    limit=max(1,min(int(limit or 100),500))
    with db() as con:
        rows=[dict(r) for r in con.execute("SELECT id,title,original_name,mime,media_kind,size,ocr_status,transcript_status,source,tags,project_id,created_at,updated_at FROM documents WHERE "+" AND ".join(where)+" ORDER BY created_at DESC LIMIT ?",[*args,limit])]
    return {"items":rows,"count":len(rows)}

@app.patch("/api/media/{did}/transcript")
def update_media_transcript(did:str,payload:dict=Body(...)):
    transcript=str(payload.get("transcript") or "").strip()[:200000]
    status="done" if transcript else "pending"
    with db() as con:
        row=con.execute("SELECT id,media_kind FROM documents WHERE id=? AND deleted=0",(did,)).fetchone()
        if not row: raise HTTPException(404,"Media not found")
        if row["media_kind"] not in ("audio","video"): raise HTTPException(400,"Transcript is only available for audio and video")
        con.execute("UPDATE documents SET transcript=?,transcript_status=?,updated_at=? WHERE id=?",(transcript,status,now(),did))
    audit("media_transcript_updated",did,"manual",f"characters={len(transcript)}")
    return {"ok":True,"id":did,"transcript_status":status,"characters":len(transcript)}

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
    allowed={"title","category","tags","notes","favorite","filename","smart_filename","entity_id","document_type","country","issue_date","expiry_date","project_id","action_status","follow_up_at"}
    updates=[];args=[]
    with db() as con:
        current=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not current:raise HTTPException(404)
    for k,v in payload.items():
        if k not in allowed:continue
        if k=="favorite":v=1 if bool(v) else 0
        if k=="entity_id":
            v=str(v or "").strip()
            if v:
                with db() as con:
                    if not con.execute("SELECT 1 FROM entities WHERE id=?",(v,)).fetchone():raise HTTPException(400,"Unknown entity")
        if k in ("document_type","country"):
            v=str(v or "").strip()[:100]
        if k in ("issue_date","expiry_date"):
            v=str(v or "").strip()
            if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}",v):raise HTTPException(400,"Date must use YYYY-MM-DD")
        if k=="action_status" and str(v or "none") not in ("none","review","waiting","done"):
            raise HTTPException(400,"Invalid document action status")
        if k=="follow_up_at": v=_clean_personal_datetime(v)
        if k=="smart_filename":
            requested=clean_filename(str(v or "").strip())
            original_ext=Path(current["original_name"]).suffix
            stem=Path(requested).stem.strip(" .-_")
            if not stem:raise HTTPException(400,"Invalid suggested filename")
            v=(stem+original_ext)[:240]
        if k=="filename":
            requested=clean_filename(str(v or "").strip())
            if not requested:raise HTTPException(400,"Filename is required")
            original_ext=Path(current["original_name"]).suffix
            requested_stem=Path(requested).stem.strip(" .-_")
            if not requested_stem:raise HTTPException(400,"Invalid filename")
            v=(requested_stem+original_ext)[:240]
            updates.extend(["original_name=?","smart_filename=?","filename_locked=1"]);args.extend([v,v])
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

@app.get("/api/documents/dashboard")
def document_dashboard():
    today=datetime.now(timezone.utc).date()
    warning=(today+timedelta(days=30)).isoformat()
    with db() as con:
        counts={
            "total":con.execute("SELECT count(*) FROM documents WHERE deleted=0").fetchone()[0],
            "review":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND (ocr_status IN ('pending','processing') OR action_status='review')").fetchone()[0],
            "waiting":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND action_status='waiting'").fetchone()[0],
            "expiring":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND expiry_date>=? AND expiry_date<=?",(today.isoformat(),warning)).fetchone()[0],
            "expired":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND expiry_date<>'' AND expiry_date<?",(today.isoformat(),)).fetchone()[0],
            "uncategorized":con.execute("SELECT count(*) FROM documents WHERE deleted=0 AND category='other'").fetchone()[0],
        }
        recent=[dict(r) for r in con.execute("SELECT id,title,document_type,expiry_date,action_status,ocr_status,created_at FROM documents WHERE deleted=0 ORDER BY created_at DESC LIMIT 8")]
        attention=[dict(r) for r in con.execute("SELECT id,title,document_type,expiry_date,action_status,ocr_status,follow_up_at FROM documents WHERE deleted=0 AND (action_status IN ('review','waiting') OR ocr_status IN ('pending','failed') OR (expiry_date<>'' AND expiry_date<=?)) ORDER BY CASE WHEN expiry_date<>'' THEN expiry_date ELSE follow_up_at END LIMIT 20",(warning,))]
    return {"counts":counts,"recent":recent,"attention":attention}

@app.post("/api/documents/{did}/personal-action")
def document_personal_action(did:str,payload:dict=Body(...)):
    kind=str(payload.get("kind") or "task").strip().lower()
    if kind not in ("task","fact"): raise HTTPException(400,"kind must be task or fact")
    with db() as con: row=con.execute("SELECT * FROM documents WHERE id=? AND deleted=0",(did,)).fetchone()
    if not row: raise HTTPException(404,"Document not found")
    title=_clean_personal_text(payload.get("title") or row["title"],240)
    details=_clean_personal_text(payload.get("details") or row["notes"] or row["ocr_text"][:3000],4000)
    project_id=_clean_personal_text(payload.get("project_id") or row["project_id"],80)
    if kind=="task":
        item=create_personal_item({"title":title,"details":details,"item_type":"document","status":"inbox","due_at":_clean_personal_datetime(payload.get("due_at")),"project_id":project_id,"document_id":did,"source":"document"})["item"]
        with db() as con:
            con.execute("UPDATE documents SET action_status='waiting',follow_up_at=?,updated_at=? WHERE id=?",(_clean_personal_datetime(payload.get("follow_up_at")),now(),did))
            _personal_link(con,"document",did,"item",item["id"],"action_from_document",100,"document")
        audit("document_task_created",did,"web",item["id"])
        return {"ok":True,"kind":"task","item":item}
    fact=create_personal_fact({"fact_type":payload.get("fact_type") or "document","label":title,"value":details,"details":details,"project_id":project_id,"source_capture_id":"document:"+did})["fact"]
    with db() as con:
        con.execute("UPDATE documents SET action_status='done',updated_at=? WHERE id=?",(now(),did))
        _personal_link(con,"document",did,"fact",fact["id"],"fact_from_document",100,"document")
    audit("document_fact_created",did,"web",fact["id"])
    return {"ok":True,"kind":"fact","fact":fact}

@app.post("/api/documents/{did}/apply-suggestion")
def apply_suggestion(did:str):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        if not row["suggested_title"]:raise HTTPException(400,"No suggestion")
        con.execute("UPDATE documents SET title=?,updated_at=? WHERE id=?",(row["suggested_title"],now(),did))
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone();fts_upsert(con,row)
    return {"ok":True}

@app.post("/api/documents/{did}/apply-smart-filename")
def apply_smart_filename(did:str,payload:dict=Body(default={})):
    with db() as con:
        row=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        filename=clean_filename(payload.get("filename") or row["smart_filename"] or "")
        if not filename:raise HTTPException(400,"No OCR filename suggestion")
        extension=Path(row["original_name"]).suffix
        stem=Path(filename).stem.strip(" .-_")
        if not stem:raise HTTPException(400,"Invalid filename")
        filename=(stem+extension)[:240]
        con.execute(
            "UPDATE documents SET original_name=?,smart_filename=?,filename_locked=0,updated_at=? WHERE id=?",
            (filename,filename,now(),did)
        )
        fresh=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        fts_upsert(con,fresh)
    audit("document_auto_renamed",did,"web",filename)
    return {"ok":True,"filename":filename}

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
        version_files=[r[0] for r in con.execute("SELECT stored_name FROM document_versions WHERE document_id=?",(did,))]
        con.execute("DELETE FROM shares WHERE document_id=?",(did,))
        try:con.execute("DELETE FROM documents_fts2 WHERE id=?",(did,))
        except Exception:pass
        con.execute("DELETE FROM documents WHERE id=?",(did,))
    (FILES/row["stored_name"]).unlink(missing_ok=True)
    for stored_name in version_files:(FILES/stored_name).unlink(missing_ok=True)
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
def retry_ocr(did:str,payload:dict=Body(default={})):
    auto_rename=bool(payload.get("auto_rename",True))
    with db() as con:
        row=con.execute("SELECT id FROM documents WHERE id=?",(did,)).fetchone()
        if not row:raise HTTPException(404)
        con.execute(
            "UPDATE documents SET ocr_status='pending',filename_locked=CASE WHEN ? THEN 0 ELSE filename_locked END,updated_at=? WHERE id=?",
            (1 if auto_rename else 0,now(),did)
        )
    return {"ok":True,"auto_rename":auto_rename}

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
        "version":"4.6",
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
    download=f"/shared/{token}/file?download=1"
    return {"ok":True,"token":token,"url":rel,"share_url":(PUBLIC_BASE_URL+rel if PUBLIC_BASE_URL else rel),
            "download_url":(PUBLIC_BASE_URL+download if PUBLIC_BASE_URL else download),"download_path":download,
            "expires_at":exp,"max_downloads":max_downloads}


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
        download=f'/shared/{x["token"]}/file?download=1'
        x["download_url"]=(PUBLIC_BASE_URL+download if PUBLIC_BASE_URL else download)
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
    @font-face{{font-family:'Noto Sans Arabic';src:url('/font-persian-regular.ttf')}}
    @font-face{{font-family:'Noto Sans Arabic';src:url('/font-persian-bold.ttf');font-weight:700}}
    *{{box-sizing:border-box}}body{{font-family:'Noto Sans Arabic',Tahoma,Arial,system-ui;background:#0b1224;color:#eef3ff;margin:0}}
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

def telegram_identity(request:Request):
    init_data=request.headers.get("X-Telegram-Init-Data","")
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(503,"Telegram Mini App is not configured")
    if not init_data or len(init_data)>16384:
        raise HTTPException(401,"Telegram authorization required")
    fields=dict(parse_qsl(init_data,keep_blank_values=True,strict_parsing=False))
    received_hash=fields.pop("hash","")
    if not received_hash:
        raise HTTPException(401,"Telegram signature is missing")
    data_check="\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret=hmac.new(b"WebAppData",TELEGRAM_BOT_TOKEN.encode(),hashlib.sha256).digest()
    calculated=hmac.new(secret,data_check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated,received_hash):
        raise HTTPException(401,"Invalid Telegram signature")
    try:
        auth_date=int(fields.get("auth_date","0"))
    except ValueError:
        raise HTTPException(401,"Invalid Telegram authorization date")
    if auth_date<=0 or abs(int(time.time())-auth_date)>TELEGRAM_INIT_MAX_AGE:
        raise HTTPException(401,"Telegram authorization expired")
    try:
        user=json.loads(fields.get("user","{}"))
    except json.JSONDecodeError:
        raise HTTPException(401,"Invalid Telegram user")
    user_id=str(user.get("id", ""))
    if not user_id:
        raise HTTPException(401,"Telegram user is missing")
    if TELEGRAM_ALLOWED_USERS and user_id not in TELEGRAM_ALLOWED_USERS:
        raise HTTPException(403,"Telegram user is not allowed")
    return user

@app.get("/api/telegram/me")
def telegram_me(request:Request):
    return {"ok":True,"user":telegram_identity(request),"version":"4.6"}

@app.get("/api/telegram/stats")
def telegram_stats(request:Request):
    telegram_identity(request);return stats()

@app.get("/api/telegram/categories")
def telegram_categories(request:Request):
    telegram_identity(request);return categories()

@app.get("/api/telegram/entities")
def telegram_entities(request:Request,q:str="",kind:str=""):
    telegram_identity(request);return entities(q,kind)

@app.post("/api/telegram/entities")
def telegram_create_entity(request:Request,payload:dict=Body(...)):
    telegram_identity(request);return create_entity(payload)

@app.patch("/api/telegram/entities/{eid}")
def telegram_update_entity(request:Request,eid:str,payload:dict=Body(...)):
    telegram_identity(request);return update_entity(eid,payload)

@app.get("/api/telegram/document-types")
def telegram_document_types(request:Request):
    telegram_identity(request);return document_types()

@app.get("/api/telegram/countries")
def telegram_countries(request:Request):
    telegram_identity(request);return countries()

@app.get("/api/telegram/activity")
def telegram_activity(request:Request,limit:int=30):
    telegram_identity(request);return activity(limit)

@app.get("/api/telegram/documents")
def telegram_documents(request:Request,q:str="",category:str="",source:str="",ocr:str="",days:int=0,scope:str="all",sort:str="newest",entity_id:str="",document_type:str="",country:str="",validity:str=""):
    telegram_identity(request);return documents(q,category,source,ocr,days,scope,sort,entity_id,document_type,country,validity)

@app.get("/api/telegram/alerts")
def telegram_alerts(request:Request,days:int=60):
    telegram_identity(request);return alerts(days)

@app.get("/api/telegram/entities/{eid}/dossier")
def telegram_entity_dossier(request:Request,eid:str):
    telegram_identity(request);return entity_dossier(eid)

@app.post("/api/telegram/entities/{eid}/requirements")
def telegram_create_requirement(request:Request,eid:str,payload:dict=Body(...)):
    telegram_identity(request);return create_requirement(eid,payload)

@app.delete("/api/telegram/entities/{eid}/requirements/{rid}")
def telegram_delete_requirement(request:Request,eid:str,rid:str):
    telegram_identity(request);return delete_requirement(eid,rid)

@app.post("/api/telegram/documents/upload")
def telegram_upload(request:Request,files:list[UploadFile]=File(...)):
    user=telegram_identity(request)
    results=[ingest_upload(file,"telegram") for file in files[:20]]
    audit("telegram_mini_upload",source=str(user.get("id","")),details=f"{len(results)} files")
    return {"ok":True,"items":results}

@app.get("/api/telegram/documents/{did}")
def telegram_document(request:Request,did:str):
    telegram_identity(request);return document(did)

@app.patch("/api/telegram/documents/{did}")
def telegram_update_document(request:Request,did:str,payload:dict=Body(...)):
    telegram_identity(request);return update_document(did,payload)

@app.delete("/api/telegram/documents/{did}")
def telegram_trash_document(request:Request,did:str):
    telegram_identity(request);return trash_document(did)

@app.post("/api/telegram/documents/{did}/restore")
def telegram_restore_document(request:Request,did:str):
    telegram_identity(request);return restore_document(did)

@app.post("/api/telegram/documents/{did}/retry-ocr")
def telegram_retry_ocr(request:Request,did:str,payload:dict=Body(default={})):
    telegram_identity(request);return retry_ocr(did,payload)

@app.post("/api/telegram/documents/{did}/apply-smart-filename")
def telegram_apply_smart_filename(request:Request,did:str,payload:dict=Body(default={})):
    telegram_identity(request);return apply_smart_filename(did,payload)

@app.post("/api/telegram/documents/{did}/share")
def telegram_create_share(request:Request,did:str,payload:dict=Body(default={})):
    telegram_identity(request);return create_share(did,payload)

@app.get("/api/telegram/documents/{did}/preview")
def telegram_preview(request:Request,did:str):
    telegram_identity(request);return preview(did)

@app.get("/api/telegram/documents/{did}/file")
def telegram_file(request:Request,did:str,download:int=0):
    telegram_identity(request);return file_view(did,download)

@app.get("/api/telegram/documents/{did}/versions")
def telegram_versions(request:Request,did:str):
    telegram_identity(request);return document_versions(did)

@app.post("/api/telegram/documents/{did}/replace")
def telegram_replace(request:Request,did:str,file:UploadFile=File(...),x_version_note:str|None=Header(None,alias="X-Version-Note")):
    telegram_identity(request);return replace_document(did,file,x_version_note)

@app.get("/api/telegram/documents/{did}/versions/{vid}/file")
def telegram_version_file(request:Request,did:str,vid:str,download:int=0):
    telegram_identity(request);return version_file(did,vid,download)

@app.get("/icon.svg")
def icon():
    return FileResponse(WEB/"icon.svg",media_type="image/svg+xml",headers={"Cache-Control":"public,max-age=86400"})

@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB/"manifest.webmanifest",media_type="application/manifest+json",headers={"Cache-Control":"no-cache"})

@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB/"sw.js",media_type="application/javascript",headers={"Cache-Control":"no-cache"})

@app.get("/font-persian-regular.ttf")
def persian_font_regular():
    return FileResponse(WEB/"fonts"/"NotoSansArabic-Regular.ttf",media_type="font/ttf",headers={"Cache-Control":"public,max-age=31536000,immutable"})

@app.get("/font-persian-bold.ttf")
def persian_font_bold():
    return FileResponse(WEB/"fonts"/"NotoSansArabic-Bold.ttf",media_type="font/ttf",headers={"Cache-Control":"public,max-age=31536000,immutable"})

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

@app.get("/api/document-types")
def document_types():
    return {"items":["شناسنامه","کارت ملی","گذرنامه","کارت اقامت","گواهینامه رانندگی","نامه حقوقی","قرارداد اجاره","بیمه","صورتحساب بانکی","نامه بانکی","مدرک تحصیلی","قرارداد کاری","فیش حقوقی","سند مالیاتی","فاکتور","قرارداد","سایر"]}

@app.get("/api/countries")
def countries():
    return {"items":[
        {"id":"IR","name":"ایران"},{"id":"AT","name":"اتریش"},{"id":"DE","name":"آلمان"},
        {"id":"IT","name":"ایتالیا"},{"id":"TR","name":"ترکیه"},{"id":"AE","name":"امارات"},
        {"id":"FR","name":"فرانسه"},{"id":"CH","name":"سوئیس"},{"id":"other","name":"سایر"}
    ]}

@app.get("/api/entities")
def entities(q:str="",kind:str=""):
    where=["1=1"];args=[]
    if q.strip():where.append("e.name LIKE ?");args.append(f"%{q.strip()}%")
    if kind in ("person","organization","other"):where.append("e.kind=?");args.append(kind)
    with db() as con:
        rows=[dict(r) for r in con.execute(f"""SELECT e.*,
            count(d.id) AS document_count FROM entities e
            LEFT JOIN documents d ON d.entity_id=e.id AND d.deleted=0
            WHERE {' AND '.join(where)} GROUP BY e.id ORDER BY e.name COLLATE NOCASE""",args)]
    return {"items":rows}

@app.post("/api/entities")
def create_entity(payload:dict=Body(...)):
    name=re.sub(r"\s+"," ",str(payload.get("name") or "")).strip()[:160]
    kind=str(payload.get("kind") or "person")
    country=str(payload.get("country") or "").strip()[:20]
    notes=str(payload.get("notes") or "").strip()[:1000]
    if not name:raise HTTPException(400,"Entity name is required")
    if kind not in ("person","organization","other"):raise HTTPException(400,"Invalid entity kind")
    with db() as con:
        duplicate=con.execute("SELECT id FROM entities WHERE name=? COLLATE NOCASE AND kind=?",(name,kind)).fetchone()
        if duplicate:raise HTTPException(409,"This entity already exists")
        eid=str(uuid.uuid4());ts=now()
        con.execute("INSERT INTO entities(id,name,kind,country,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(eid,name,kind,country,notes,ts,ts))
        row=con.execute("SELECT * FROM entities WHERE id=?",(eid,)).fetchone()
    audit("entity_created",source="web",details=f"{kind}:{name}")
    return {"ok":True,"item":dict(row)}

@app.patch("/api/entities/{eid}")
def update_entity(eid:str,payload:dict=Body(...)):
    allowed={"name","kind","country","notes"};updates=[];args=[]
    for key,value in payload.items():
        if key not in allowed:continue
        value=str(value or "").strip()
        if key=="name" and not value:raise HTTPException(400,"Entity name is required")
        if key=="kind" and value not in ("person","organization","other"):raise HTTPException(400,"Invalid entity kind")
        updates.append(f"{key}=?");args.append(value[:1000] if key=="notes" else value[:160])
    if not updates:return {"ok":True}
    updates.append("updated_at=?");args.extend([now(),eid])
    try:
        with db() as con:
            if not con.execute("SELECT 1 FROM entities WHERE id=?",(eid,)).fetchone():raise HTTPException(404)
            con.execute(f"UPDATE entities SET {','.join(updates)} WHERE id=?",args)
            row=con.execute("SELECT * FROM entities WHERE id=?",(eid,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(409,"This entity already exists")
    audit("entity_updated",source="web",details=eid)
    return {"ok":True,"item":dict(row)}

@app.get("/api/entities/{eid}/dossier")
def entity_dossier(eid:str):
    with db() as con:
        entity=con.execute("SELECT * FROM entities WHERE id=?",(eid,)).fetchone()
        if not entity:raise HTTPException(404)
        documents=[dict(r) for r in con.execute("""SELECT id,title,original_name,document_type,country,
            issue_date,expiry_date,version_no,ocr_status,created_at,updated_at
            FROM documents WHERE entity_id=? AND deleted=0 ORDER BY document_type,created_at DESC""",(eid,))]
        requirements=[dict(r) for r in con.execute(
            "SELECT * FROM entity_requirements WHERE entity_id=? ORDER BY document_type,country",(eid,)
        )]
    for item in documents:item["validity_status"]=document_validity(item.get("expiry_date"))
    present={(d["document_type"],d["country"]) for d in documents}
    present_any={d["document_type"] for d in documents}
    for item in requirements:
        item["fulfilled"]=(item["document_type"],item["country"]) in present if item["country"] else item["document_type"] in present_any
    return {"entity":dict(entity),"documents":documents,"requirements":requirements,
            "summary":{"documents":len(documents),"required":len(requirements),
                       "missing":sum(1 for x in requirements if not x["fulfilled"]),
                       "expired":sum(1 for x in documents if x["validity_status"]=="expired"),
                       "expiring":sum(1 for x in documents if x["validity_status"]=="expiring")}}

@app.post("/api/entities/{eid}/requirements")
def create_requirement(eid:str,payload:dict=Body(...)):
    document_type=str(payload.get("document_type") or "").strip()[:100]
    country=str(payload.get("country") or "").strip()[:20]
    notes=str(payload.get("notes") or "").strip()[:500]
    if not document_type:raise HTTPException(400,"Document type is required")
    rid=str(uuid.uuid4())
    try:
        with db() as con:
            if not con.execute("SELECT 1 FROM entities WHERE id=?",(eid,)).fetchone():raise HTTPException(404)
            con.execute("INSERT INTO entity_requirements(id,entity_id,document_type,country,notes,created_at) VALUES(?,?,?,?,?,?)",
                        (rid,eid,document_type,country,notes,now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409,"Requirement already exists")
    audit("requirement_created",source="web",details=f"{eid}:{document_type}:{country}")
    return {"ok":True,"id":rid}

@app.delete("/api/entities/{eid}/requirements/{rid}")
def delete_requirement(eid:str,rid:str):
    with db() as con:
        cur=con.execute("DELETE FROM entity_requirements WHERE id=? AND entity_id=?",(rid,eid))
        if not cur.rowcount:raise HTTPException(404)
    audit("requirement_deleted",source="web",details=f"{eid}:{rid}")
    return {"ok":True}

@app.get("/api/alerts")
def alerts(days:int=60):
    days=max(1,min(days,365));today=datetime.now(timezone.utc).date();until=today+timedelta(days=days)
    with db() as con:
        expiry=[dict(r) for r in con.execute("""SELECT d.id,d.title,d.original_name,d.document_type,d.country,
            d.expiry_date,d.entity_id,coalesce(e.name,'') entity_name
            FROM documents d LEFT JOIN entities e ON e.id=d.entity_id
            WHERE d.deleted=0 AND d.expiry_date<>'' AND d.expiry_date<=?
            ORDER BY d.expiry_date""",(until.isoformat(),))]
        missing=[dict(r) for r in con.execute("""SELECT r.id,r.entity_id,e.name entity_name,r.document_type,r.country,r.notes
            FROM entity_requirements r JOIN entities e ON e.id=r.entity_id
            WHERE NOT EXISTS(SELECT 1 FROM documents d WHERE d.deleted=0 AND d.entity_id=r.entity_id
              AND d.document_type=r.document_type AND (r.country='' OR d.country=r.country))
            ORDER BY e.name,r.document_type""")]
    for item in expiry:
        item["validity_status"]=document_validity(item["expiry_date"])
        item["days_left"]=(datetime.strptime(item["expiry_date"][:10],"%Y-%m-%d").date()-today).days
    return {"expiry":expiry,"missing":missing,"days":days}

@app.get("/api/documents/{did}/versions")
def document_versions(did:str):
    with db() as con:
        current=con.execute("SELECT id,version_no,original_name,mime,size,sha256,updated_at FROM documents WHERE id=?",(did,)).fetchone()
        if not current:raise HTTPException(404)
        older=[dict(r) for r in con.execute("""SELECT id,version_no,original_name,mime,size,sha256,created_at,note
            FROM document_versions WHERE document_id=? ORDER BY version_no DESC""",(did,))]
    return {"current":dict(current),"items":older}

@app.post("/api/documents/{did}/replace")
def replace_document(did:str,file:UploadFile=File(...),x_version_note:str|None=Header(None,alias="X-Version-Note")):
    with db() as con:
        current=con.execute("SELECT * FROM documents WHERE id=? AND deleted=0",(did,)).fetchone()
    if not current:raise HTTPException(404)
    saved=hash_and_store(file.file,clean_filename(file.filename or current["original_name"]))
    if saved.get("duplicate"):raise HTTPException(409,"This file already exists in the archive")
    vid=str(uuid.uuid4());new_version=int(current["version_no"] or 1)+1;ts=now()
    try:
        with db() as con:
            con.execute("""INSERT INTO document_versions
                (id,document_id,version_no,stored_name,original_name,mime,size,sha256,created_at,note)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (vid,did,current["version_no"],current["stored_name"],current["original_name"],current["mime"],
                 current["size"],current["sha256"],ts,str(x_version_note or "")[:500]))
            new_name=clean_filename(file.filename or current["original_name"])
            con.execute("""UPDATE documents SET stored_name=?,original_name=?,source_name=?,mime=?,size=?,sha256=?,
                version_no=?,ocr_status='pending',ocr_text='',updated_at=? WHERE id=?""",
                (saved["stored"],new_name,new_name,saved["mime"],saved["size"],saved["sha256"],new_version,ts,did))
            fresh=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone();fts_upsert(con,fresh)
    except Exception:
        (FILES/saved["stored"]).unlink(missing_ok=True)
        raise
    (PREV/f"{did}.jpg").unlink(missing_ok=True)
    audit("document_replaced",did,"web",f"version {new_version}")
    return {"ok":True,"version_no":new_version,"queued":True}

@app.get("/api/documents/{did}/versions/{vid}/file")
def version_file(did:str,vid:str,download:int=0):
    with db() as con:
        row=con.execute("SELECT * FROM document_versions WHERE id=? AND document_id=?",(vid,did)).fetchone()
    if not row:raise HTTPException(404)
    path=FILES/row["stored_name"]
    if not path.exists():raise HTTPException(404)
    return FileResponse(path,media_type=row["mime"],filename=row["original_name"],
                        content_disposition_type="attachment" if download else "inline")

# Loaded after route definitions so integrations reuse the existing item API.
from personal_integrations import install as install_personal_integrations
personal_start, personal_stop = install_personal_integrations(app,ROOT,WEB,db,create_personal_item,capture_personal_item)
from personal_assistant import install as install_personal_assistant
personal_v2_start, personal_v2_analyze = install_personal_assistant(app,ROOT,db,capture_personal_item,create_personal_item,create_personal_fact,now)

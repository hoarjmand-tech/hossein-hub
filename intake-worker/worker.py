import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

INBOX=Path(os.getenv("INBOX_PATH","/inbox"))
PROCESSED=Path(os.getenv("PROCESSED_PATH","/processed"))
ERRORS=Path(os.getenv("ERROR_PATH","/errors"))
API=os.getenv("ARCHIVE_API","http://archive:8080").rstrip("/")
INTERVAL=max(2,int(os.getenv("SCAN_INTERVAL","5")))
STABLE_SECONDS=max(2,int(os.getenv("STABLE_SECONDS","8")))
MAX_MB=max(1,int(os.getenv("MAX_FILE_MB","100")))
ALLOWED={".pdf",".jpg",".jpeg",".png",".webp",".tif",".tiff"}
STATE={}

for directory in (INBOX,PROCESSED,ERRORS):
    directory.mkdir(parents=True,exist_ok=True)


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def unique_destination(directory,path):
    candidate=directory/path.name
    if not candidate.exists():
        return candidate
    digest=hashlib.sha256(str(path).encode()).hexdigest()[:8]
    return directory/f"{path.stem}-{timestamp()}-{digest}{path.suffix.lower()}"


def stable(path):
    try:
        stat=path.stat()
    except FileNotFoundError:
        return False
    key=str(path)
    current=(stat.st_size,stat.st_mtime_ns)
    previous=STATE.get(key)
    now=time.monotonic()
    if not previous or previous[:2]!=current:
        STATE[key]=(*current,now)
        return False
    return now-previous[2]>=STABLE_SECONDS


def upload(path):
    if path.stat().st_size>MAX_MB*1024*1024:
        raise RuntimeError(f"file exceeds {MAX_MB} MB")
    mime="application/pdf" if path.suffix.lower()==".pdf" else "application/octet-stream"
    with path.open("rb") as handle:
        response=requests.post(
            f"{API}/api/documents/upload",
            files={"files":(path.name,handle,mime)},
            headers={"X-Archive-Source":"scanner_folder"},
            timeout=300,
        )
    response.raise_for_status()
    data=response.json()
    item=(data.get("items") or [{}])[0]
    return item


def process(path):
    try:
        result=upload(path)
        destination=unique_destination(PROCESSED,path)
        shutil.move(str(path),destination)
        STATE.pop(str(path),None)
        print(json.dumps({"event":"imported","file":path.name,"result":result},ensure_ascii=False),flush=True)
    except Exception as exc:
        destination=unique_destination(ERRORS,path)
        try:
            shutil.move(str(path),destination)
        except Exception:
            destination=path
        STATE.pop(str(path),None)
        print(json.dumps({"event":"failed","file":path.name,"error":str(exc),"moved_to":str(destination)},ensure_ascii=False),flush=True)


def main():
    print(json.dumps({"service":"document-intake","inbox":str(INBOX),"api":API},ensure_ascii=False),flush=True)
    while True:
        try:
            for path in sorted(INBOX.iterdir()):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.suffix.lower() not in ALLOWED:
                    continue
                if stable(path):
                    process(path)
        except Exception as exc:
            print(json.dumps({"event":"worker_error","error":str(exc)},ensure_ascii=False),flush=True)
        time.sleep(INTERVAL)


if __name__=="__main__":
    main()

import hmac, os, uuid
from pathlib import Path
from fastapi import APIRouter, File, Header, HTTPException, UploadFile, Query
from .core import ARCHIVE_ROOT, MAX_UPLOAD, secret

r = APIRouter(prefix="/api/google-drive-push")

TOKEN = secret(os.getenv("DRIVE_PUSH_TOKEN_FILE","/run/secrets/drive_push_token"))
INBOX = ARCHIVE_ROOT / "drive-inbox"
INBOX.mkdir(parents=True, exist_ok=True)

@r.post("/upload")
def upload(
    file: UploadFile = File(...),
    x_drive_token: str = Header(..., alias="X-Drive-Token"),
    x_drive_file_id: str | None = Header(None, alias="X-Drive-File-Id"),
):
    if not TOKEN or not hmac.compare_digest(x_drive_token, TOKEN):
        raise HTTPException(401, "Unauthorized")

    name = Path(file.filename or "document").name
    safe_id = "".join(c for c in (x_drive_file_id or str(uuid.uuid4())) if c.isalnum() or c in "-_")[:160]
    target = INBOX / f"gdrive__{safe_id}__{name}"

    # If the same Drive file was already queued and still exists, do not duplicate the queue entry.
    if target.exists():
        return {"ok": True, "queued": False, "reason": "already_queued"}

    total = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "File too large")
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return {"ok": True, "queued": True, "name": name, "bytes": total}


@r.get("/rename-jobs")
def rename_jobs(x_drive_token: str = Header(..., alias="X-Drive-Token")):
    if not TOKEN or not hmac.compare_digest(x_drive_token, TOKEN):
        raise HTTPException(401, "Unauthorized")
    return {"jobs":[], "mode":"safe-import", "message":"Automatic Drive renaming is disabled."}

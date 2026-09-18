# Hossein Hub

Private-first personal document archive. Source code only; never commit documents, database files, secrets, exports, OCR data, or backups.

## Archive module
FastAPI + PostgreSQL document registry with SHA-256 duplicate detection, metadata, cases, tags, expiry tracking, soft-delete/trash/restore, audit events, full-text metadata search, safe local storage and download endpoints.

## Deploy
Copy .env.example to .env and set a strong API key and DB password. Then:
```bash
docker compose up -d --build
curl http://127.0.0.1:8080/health
```
API docs: http://127.0.0.1:8080/docs


## Remote access
Sensitive administration is designed for Tailscale rather than direct Internet exposure.
After normal deployment, enroll the host once with `bash remote-access.sh`.
The LAN application remains available on `192.168.1.35:8080`. Do not port-forward SSH or the archive API directly from the Internet.

## Backups
Run `bash backup.sh` to create a timestamped PostgreSQL dump, archive snapshot, and SHA-256 manifest under `backups/`.

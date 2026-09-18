# Hossein Hub 1.0
Private digital archive and personal operations platform.

## Archive 1.0
Authentication with Argon2 and server sessions; CSRF protection; login throttling; PDF/image upload with server-side MIME validation; SHA-256 duplicate detection; asynchronous Persian/English OCR; thumbnails; metadata; tags; people; cases; versions; original/translation/signed kinds; document relations; full-text/OCR search; favorites; expiry tracking; reminders; notification center; recycle bin/restore/permanent purge API; audit trail; ZIP export; expiring/revocable share links; responsive PWA.

## Operations
PostgreSQL, FastAPI, dedicated OCR worker, Nginx security proxy, Tailscale private HTTPS, daily verified database/archive backups, restore script, health-check script and Docker health monitoring.

## Deploy
`cd /opt/hossein-hub && bash deploy.sh && sudo bash install-maintenance.sh`

## Remote HTTPS
`bash remote-access.sh`

## Verify
`bash healthcheck.sh`

## Restore
`sudo bash restore.sh /opt/hossein-hub/backups/<timestamp>`

Secrets and user documents must never be committed to Git.

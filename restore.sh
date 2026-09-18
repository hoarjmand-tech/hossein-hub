#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub;cd "$ROOT"
B="${1:-}"
if [ -z "$B" ] || [ ! -d "$B" ]; then echo "Usage: sudo bash restore.sh /opt/hossein-hub/backups/YYYYMMDD-HHMMSS"; exit 2; fi
cd "$B";sha256sum -c SHA256SUMS
cd "$ROOT";docker compose -f docker-compose.yml stop archive-api ocr-worker nginx
mv archive "archive.pre-restore-$(date +%Y%m%d-%H%M%S)"
tar -xzf "$B/archive.tar.gz" -C "$ROOT"
gunzip -c "$B/database.sql.gz" | docker exec -i hossein-hub-postgres psql -U "${POSTGRES_USER:-hubadmin}" -d "${POSTGRES_DB:-hossein_hub}" >/dev/null
docker compose -f docker-compose.yml up -d
echo "RESTORE OK"

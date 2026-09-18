#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub;cd "$ROOT";set -a;source .env;set +a
B="${1:-}";KEY="$ROOT/secrets/backup_key"
[ -d "$B" ] || { echo "Usage: sudo bash restore.sh /opt/hossein-hub/backups/YYYYMMDD-HHMMSS";exit 2; }
[ -s "$KEY" ] || { echo "Missing backup encryption key";exit 3; }
(cd "$B" && sha256sum -c SHA256SUMS)
echo "PRE-RESTORE SAFETY BACKUP"
bash "$ROOT/backup.sh"
TMP=$(mktemp -d);trap 'rm -rf "$TMP"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$B/database.sql.gz.enc" -out "$TMP/database.sql.gz" -pass file:"$KEY"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$B/archive.tar.gz.enc" -out "$TMP/archive.tar.gz" -pass file:"$KEY"
if [ -f "$B/system.tar.gz.enc" ]; then
 openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$B/system.tar.gz.enc" -out "$TMP/system.tar.gz" -pass file:"$KEY"
fi
docker compose -f docker-compose.yml stop archive-api ocr-worker nginx telegram-bot
STAMP=$(date +%Y%m%d-%H%M%S);[ ! -d archive ]||mv archive "archive.pre-restore-$STAMP"
tar -xzf "$TMP/archive.tar.gz" -C "$ROOT"
if [ -f "$TMP/system.tar.gz" ]; then tar -xzf "$TMP/system.tar.gz" -C "$ROOT"; fi
gunzip -c "$TMP/database.sql.gz" | docker exec -i hossein-hub-postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-hubadmin}" -d "${POSTGRES_DB:-hossein_hub}" >/dev/null
docker compose -f docker-compose.yml up -d
echo "RESTORE OK"

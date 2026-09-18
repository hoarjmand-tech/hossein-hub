#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub;cd "$ROOT";set -a;source .env;set +a
KEY="$ROOT/secrets/backup_key"
if [ ! -s "$KEY" ];then umask 077;openssl rand -base64 48 > "$KEY";chmod 600 "$KEY";fi
TS=$(date +%Y%m%d-%H%M%S);DEST="$ROOT/backups/$TS";TMP=$(mktemp -d);trap 'rm -rf "$TMP"' EXIT;mkdir -p "$DEST"
docker exec hossein-hub-postgres pg_dump --clean --if-exists -U "${POSTGRES_USER:-hubadmin}" "${POSTGRES_DB:-hossein_hub}" | gzip > "$TMP/database.sql.gz"
tar -czf "$TMP/archive.tar.gz" archive
for F in database.sql.gz archive.tar.gz;do openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -in "$TMP/$F" -out "$DEST/$F.enc" -pass file:"$KEY";done
sha256sum "$DEST/"*.enc > "$DEST/SHA256SUMS"
find "$ROOT/backups" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "ENCRYPTED BACKUP OK: $DEST"

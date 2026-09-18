#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub;cd "$ROOT";TS=$(date +%Y%m%d-%H%M%S);DEST="$ROOT/backups/$TS";mkdir -p "$DEST"
docker exec hossein-hub-postgres pg_dump -U "${POSTGRES_USER:-hubadmin}" "${POSTGRES_DB:-hossein_hub}" | gzip > "$DEST/database.sql.gz"
tar -czf "$DEST/archive.tar.gz" archive
sha256sum "$DEST/"* > "$DEST/SHA256SUMS"
find "$ROOT/backups" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "BACKUP OK: $DEST"

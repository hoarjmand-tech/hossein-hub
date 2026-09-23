#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/hossein-hub"
BACKUP_ROOT="$PROJECT_DIR/backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_ROOT/personal-$STAMP"
SNAPSHOT_IN_CONTAINER="/data/tmp/personal-backup-$STAMP.sqlite"

cd "$PROJECT_DIR"
mkdir -p "$TARGET"

sudo docker exec hossein-archive python -c "import sqlite3; s=sqlite3.connect('/data/archive.db'); d=sqlite3.connect('$SNAPSHOT_IN_CONTAINER'); s.backup(d); d.close(); s.close()"
sudo docker cp "hossein-archive:$SNAPSHOT_IN_CONTAINER" "$TARGET/archive.sqlite"
sudo docker exec hossein-archive python -c "from pathlib import Path; Path('$SNAPSHOT_IN_CONTAINER').unlink(missing_ok=True)"

tar --exclude='archive.db' --exclude='archive.db-wal' --exclude='archive.db-shm' -czf "$TARGET/archive-data.tar.gz" archive_data
sha256sum "$TARGET/archive.sqlite" "$TARGET/archive-data.tar.gz" > "$TARGET/SHA256SUMS"

curl -fsS http://127.0.0.1:8188/api/personal/v2/export > "$TARGET/personal-export.json"
echo "Backup created: $TARGET"

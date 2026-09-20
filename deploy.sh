#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT/backups/release-$STAMP"

cd "$PROJECT"
echo "===== PRE-FLIGHT ====="
test -f docker-compose.yml
test -f archive_v2/main.py
test -f intake-worker/worker.py
test -f telegram-bot/bot.py

mkdir -p "$BACKUP" scanner_inbox scanner_processed scanner_errors secrets
cp -a docker-compose.yml archive_v2 "$BACKUP/"

if [[ -f archive_data/archive.db ]]; then
  python3 - "$PROJECT/archive_data/archive.db" "$BACKUP/archive.db" <<'PY'
import sqlite3
import sys
source=sqlite3.connect(sys.argv[1])
target=sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created $PROJECT/.env. Telegram is idle until its token is added."
fi

# Migrate the previous LAN default without changing a custom public URL.
if grep -q '^PUBLIC_BASE_URL=http://192\.168\.1\.35:8080$' .env; then
  sed -i 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=http://192.168.1.35:8188#' .env
  echo "Updated default PUBLIC_BASE_URL to port 8188"
fi

if [[ ! -f secrets/drive_push_token ]]; then
  umask 077
  python3 - <<'PY' > secrets/drive_push_token
import secrets
print(secrets.token_urlsafe(48))
PY
fi

python3 -m py_compile archive_v2/*.py intake-worker/*.py telegram-bot/*.py
docker compose config --quiet

echo "===== BUILD ====="
docker compose build
echo "===== START ====="
docker compose up -d --remove-orphans

echo "===== HEALTH ====="
for attempt in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8188/health >/tmp/hossein-archive-health.json 2>/dev/null; then
    cat /tmp/hossein-archive-health.json
    echo
    docker compose ps
    echo "DEPLOY COMPLETED SUCCESSFULLY"
    echo "Archive: http://192.168.1.35:8188"
    echo "Scanner inbox: $PROJECT/scanner_inbox"
    echo "Backup: $BACKUP"
    exit 0
  fi
  echo "Waiting for archive... $attempt/40"
  sleep 3
done

echo "ERROR: Archive health check failed"
docker compose ps
docker compose logs --tail 200 archive
echo "Backup: $BACKUP"
exit 1

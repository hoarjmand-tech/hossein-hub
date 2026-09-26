#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT/backups/release-$STAMP"

cd "$PROJECT"
echo "===== PRE-FLIGHT ====="
test -f docker-compose.yml
test -f archive_v2/main.py
test -s archive_v2/web/home.html
test -s archive_v2/web/personal.html
test -s archive_v2/web/work.html
test -s archive_v2/web/index.html
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
if grep -q '^PUBLIC_BASE_URL=http://192\.168\.1\.35:8080
if [[ ! -f secrets/drive_push_token ]]; then
  umask 077
  python3 - <<'PY' > secrets/drive_push_token
import secrets
print(secrets.token_urlsafe(48))
PY
fi

COMPOSE=(docker compose)
if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.' .env; then
  COMPOSE+=(--profile cloudflare)
fi

python3 -m py_compile archive_v2/*.py intake-worker/*.py telegram-bot/*.py
"${COMPOSE[@]}" config --quiet

echo "===== BUILD ====="
"${COMPOSE[@]}" build
echo "===== START ====="
"${COMPOSE[@]}" up -d --remove-orphans

echo "===== HEALTH ====="
HEALTH_FILE="$(mktemp)"
trap 'rm -f "$HEALTH_FILE"' EXIT
for attempt in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8188/health >"$HEALTH_FILE" 2>/dev/null; then
    cat "$HEALTH_FILE"
    echo
    "${COMPOSE[@]}" ps
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
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail 200 archive
echo "Backup: $BACKUP"
exit 1
 .env; then
  sed -i 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=http://192.168.1.35:8188#' .env
  echo "Updated default PUBLIC_BASE_URL to port 8188"
fi

# Remove the old hard-coded Google Drive root so the browser starts at real My Drive.
if grep -q '^DRIVE_ROOT_FOLDER_ID=1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP
if [[ ! -f secrets/drive_push_token ]]; then
  umask 077
  python3 - <<'PY' > secrets/drive_push_token
import secrets
print(secrets.token_urlsafe(48))
PY
fi

COMPOSE=(docker compose)
if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.' .env; then
  COMPOSE+=(--profile cloudflare)
fi

python3 -m py_compile archive_v2/*.py intake-worker/*.py telegram-bot/*.py
"${COMPOSE[@]}" config --quiet

echo "===== BUILD ====="
"${COMPOSE[@]}" build
echo "===== START ====="
"${COMPOSE[@]}" up -d --remove-orphans

echo "===== HEALTH ====="
HEALTH_FILE="$(mktemp)"
trap 'rm -f "$HEALTH_FILE"' EXIT
for attempt in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8188/health >"$HEALTH_FILE" 2>/dev/null; then
    cat "$HEALTH_FILE"
    echo
    "${COMPOSE[@]}" ps
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
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail 200 archive
echo "Backup: $BACKUP"
exit 1
 .env; then
  sed -i 's#^DRIVE_ROOT_FOLDER_ID=.*#DRIVE_ROOT_FOLDER_ID=#' .env
  echo "Reset DRIVE_ROOT_FOLDER_ID to My Drive root"
fi

if [[ ! -f secrets/drive_push_token ]]; then
  umask 077
  python3 - <<'PY' > secrets/drive_push_token
import secrets
print(secrets.token_urlsafe(48))
PY
fi

COMPOSE=(docker compose)
if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.' .env; then
  COMPOSE+=(--profile cloudflare)
fi

python3 -m py_compile archive_v2/*.py intake-worker/*.py telegram-bot/*.py
"${COMPOSE[@]}" config --quiet

echo "===== BUILD ====="
"${COMPOSE[@]}" build
echo "===== START ====="
"${COMPOSE[@]}" up -d --remove-orphans

echo "===== HEALTH ====="
HEALTH_FILE="$(mktemp)"
trap 'rm -f "$HEALTH_FILE"' EXIT
for attempt in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8188/health >"$HEALTH_FILE" 2>/dev/null; then
    cat "$HEALTH_FILE"
    echo
    "${COMPOSE[@]}" ps
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
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail 200 archive
echo "Backup: $BACKUP"
exit 1

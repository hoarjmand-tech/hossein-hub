#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
cd "$ROOT"
echo "[1/7] Fetch"
git fetch origin main
echo "[2/7] Preserve runtime"
mkdir -p /tmp/hossein-hub-deploy
cp -a .env /tmp/hossein-hub-deploy/.env 2>/dev/null || true
cp -a secrets /tmp/hossein-hub-deploy/secrets 2>/dev/null || true
echo "[3/7] Sync source"
git reset --hard origin/main
test -f /tmp/hossein-hub-deploy/.env && cp -a /tmp/hossein-hub-deploy/.env .env || true
test -d /tmp/hossein-hub-deploy/secrets && cp -a /tmp/hossein-hub-deploy/secrets/. secrets/ || true
echo "[4/7] Validate"
test -f .env || { echo "ERROR: .env missing"; exit 1; }
test -d postgres || mkdir -p postgres
mkdir -p archive/{documents,trash,import,exports} backups logs secrets
echo "[5/7] Build"
docker compose -f docker-compose.yml build
echo "[6/7] Start"
docker compose -f docker-compose.yml up -d --remove-orphans
echo "[7/7] Health"
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:8080/health >/tmp/hossein-hub-health.json 2>/dev/null; then
    cat /tmp/hossein-hub-health.json; echo; echo "DEPLOY OK"; exit 0
  fi
  sleep 2
done
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs --tail=100 archive-api
echo "DEPLOY FAILED"
exit 1

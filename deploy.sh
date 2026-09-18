#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub; cd "$ROOT"
echo "[1/8] Fetch"; git fetch origin main
echo "[2/8] Preserve runtime"; mkdir -p /tmp/hossein-hub-deploy; cp -a .env /tmp/hossein-hub-deploy/.env 2>/dev/null||true; cp -a secrets /tmp/hossein-hub-deploy/secrets 2>/dev/null||true
echo "[3/8] Sync"; git reset --hard origin/main; cp -a /tmp/hossein-hub-deploy/.env .env 2>/dev/null||true; test -d /tmp/hossein-hub-deploy/secrets && cp -a /tmp/hossein-hub-deploy/secrets/. secrets/||true
chmod +x deploy.sh 2>/dev/null||true
echo "[4/8] Runtime"; mkdir -p archive/{documents,previews,trash,import,exports} backups logs secrets
echo "[5/8] Build"; docker compose -f docker-compose.yml build
echo "[6/8] Start"; docker compose -f docker-compose.yml up -d --remove-orphans
echo "[7/8] Health"; for i in {1..45};do if curl -fsS http://127.0.0.1:8080/health >/tmp/hub-health 2>/dev/null;then cat /tmp/hub-health;echo;echo "DEPLOY OK";exit 0;fi;sleep 2;done
echo "[8/8] Diagnostics";docker compose -f docker-compose.yml ps;docker compose -f docker-compose.yml logs --tail=120 archive-api;exit 1

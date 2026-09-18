#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub;cd "$ROOT"
echo "[1/10] Fetch";git fetch origin main
echo "[2/10] Preserve runtime";mkdir -p /tmp/hossein-hub-deploy;cp -a .env /tmp/hossein-hub-deploy/.env 2>/dev/null||true;cp -a secrets /tmp/hossein-hub-deploy/secrets 2>/dev/null||true
echo "[3/10] Sync";git reset --hard origin/main;cp -a /tmp/hossein-hub-deploy/.env .env 2>/dev/null||true;test -d /tmp/hossein-hub-deploy/secrets&&cp -a /tmp/hossein-hub-deploy/secrets/. secrets/||true;chmod +x deploy.sh backup.sh restore.sh healthcheck.sh remote-access.sh install-maintenance.sh 2>/dev/null||true
echo "[4/10] Runtime";mkdir -p archive/{documents,previews,trash,import,exports} backups logs secrets config/nginx data/tailscale;chmod 700 secrets
echo "[5/10] API secret";if [ ! -s secrets/hub_api_key ];then umask 077;openssl rand -hex 32 > secrets/hub_api_key;echo "Created secrets/hub_api_key";fi;chmod 600 secrets/hub_api_key secrets/postgres_password
echo "[6/10] Network";docker network inspect hossein-hub-backend >/dev/null 2>&1||docker network create hossein-hub-backend
echo "[7/10] Validate";python3 -m compileall -q app/backend/app
echo "[7/10] Build"
if [ -f compose.yml ]; then mv compose.yml compose.yml.legacy-disabled; fi
echo "[10/10] Compose cleanup";docker compose -f docker-compose.yml build
echo "[8/10] Start";docker compose -f docker-compose.yml up -d --remove-orphans
echo "[9/10] Health";for i in {1..45};do if curl -fsS http://192.168.1.35:8080/health >/tmp/hub-health 2>/dev/null;then cat /tmp/hub-health;echo;echo "DEPLOY OK";echo "API key is stored only in /opt/hossein-hub/secrets/hub_api_key";exit 0;fi;sleep 2;done
docker compose -f docker-compose.yml ps;docker compose -f docker-compose.yml logs --tail=150 archive-api ocr-worker;exit 1

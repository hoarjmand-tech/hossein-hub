#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/hossein-hub
cd "$ROOT"

echo "[1/12] Sync source"
git fetch origin main
mkdir -p /tmp/hossein-hub-runtime
cp -a .env /tmp/hossein-hub-runtime/.env 2>/dev/null || true
cp -a secrets /tmp/hossein-hub-runtime/secrets 2>/dev/null || true
git reset --hard origin/main
cp -a /tmp/hossein-hub-runtime/.env .env 2>/dev/null || true
if [ -d /tmp/hossein-hub-runtime/secrets ]; then
  mkdir -p secrets
  cp -a /tmp/hossein-hub-runtime/secrets/. secrets/ 2>/dev/null || true
fi

echo "[2/12] Runtime directories"
mkdir -p archive/{documents,previews,trash,import,exports} backups logs data/tailscale secrets
chmod 700 secrets || true

echo "[3/12] Required secrets"
[ -s secrets/postgres_password ] || { echo "Missing secrets/postgres_password"; exit 10; }
[ -s secrets/hub_api_key ] || { umask 077; openssl rand -hex 32 > secrets/hub_api_key; }
[ -s secrets/backup_key ] || { umask 077; openssl rand -base64 48 > secrets/backup_key; }
[ -e secrets/telegram_admin_id ] || { umask 077; : > secrets/telegram_admin_id; }
if [ ! -s secrets/telegram_bot_token ]; then
  echo "Missing secrets/telegram_bot_token"
  exit 11
fi

echo "[4/12] Telegram relay"
if [ ! -s secrets/telegram_relay_ed25519 ]; then
  echo "Missing secrets/telegram_relay_ed25519"
  exit 12
fi
sudo install -m 0644 systemd/hossein-hub-telegram-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hossein-hub-telegram-relay
for i in {1..15}; do
  if ss -lnt | grep -q '127.0.0.1:10808'; then break; fi
  sleep 1
done
ss -lnt | grep -q '127.0.0.1:10808' || { echo "Telegram relay not listening"; exit 13; }

echo "[5/12] Maintenance"
sudo install -m 0644 systemd/hossein-hub-backup.service /etc/systemd/system/
sudo install -m 0644 systemd/hossein-hub-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hossein-hub-backup.timer

echo "[6/12] Docker network"
docker network inspect hossein-hub-backend >/dev/null 2>&1 || docker network create hossein-hub-backend

echo "[7/12] Validate Python"
python3 -m compileall -q app/backend/app
python3 -m compileall -q app/backend/tests 2>/dev/null || true

echo "[8/12] Disable legacy compose"
[ ! -f compose.yml ] || mv -f compose.yml compose.yml.legacy-disabled

echo "[9/12] Build"
docker compose -f docker-compose.yml build

echo "[10/12] Start"
docker compose -f docker-compose.yml up -d --remove-orphans

echo "[11/12] Wait for health"
for i in {1..60}; do
  if curl -fsS http://192.168.1.35:8080/health >/tmp/hossein-hub-health 2>/dev/null; then
    A=$(docker inspect -f '{{.State.Status}}' hossein-hub-archive 2>/dev/null || true)
    O=$(docker inspect -f '{{.State.Status}}' hossein-hub-ocr 2>/dev/null || true)
    M=$(docker inspect -f '{{.State.Status}}' hossein-hub-monitor 2>/dev/null || true)
    T=$(docker inspect -f '{{.State.Status}}' hossein-hub-telegram 2>/dev/null || true)
    N=$(docker inspect -f '{{.State.Status}}' hossein-hub-nginx 2>/dev/null || true)
    P=$(docker inspect -f '{{.State.Health.Status}}' hossein-hub-postgres 2>/dev/null || true)
    if [ "$A" = running ] && [ "$O" = running ] && [ "$M" = running ] && [ "$T" = running ] && [ "$N" = running ] && [ "$P" = healthy ]; then
      break
    fi
  fi
  sleep 2
done

echo "[12/12] Final status"
if ! find "$ROOT/backups" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
  echo "Initial encrypted backup"
  bash "$ROOT/backup.sh"
fi
docker compose -f docker-compose.yml ps
echo
curl -fsS http://192.168.1.35:8080/health && echo
echo
systemctl is-active hossein-hub-telegram-relay
systemctl is-active hossein-hub-backup.timer
echo
echo "Hossein Hub: https://hossein-hub.tailf8fccb.ts.net"
echo "ONE-SHOT SETUP OK"

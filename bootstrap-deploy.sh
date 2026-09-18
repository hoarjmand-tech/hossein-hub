#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
mkdir -p /tmp/hossein-hub-bootstrap
cp -a .env /tmp/hossein-hub-bootstrap/.env 2>/dev/null || true
cp -a secrets /tmp/hossein-hub-bootstrap/secrets 2>/dev/null || true
cp -a compose.yml /tmp/hossein-hub-bootstrap/compose.yml 2>/dev/null || true
git fetch origin main
rm -f app/backend/Dockerfile app/backend/main.py app/backend/requirements.txt
git checkout -B main origin/main
test -f /tmp/hossein-hub-bootstrap/.env && cp -a /tmp/hossein-hub-bootstrap/.env .env || true
test -d /tmp/hossein-hub-bootstrap/secrets && cp -a /tmp/hossein-hub-bootstrap/secrets/. secrets/ || true
chmod +x deploy.sh
echo "BOOTSTRAP OK"
echo "Now run: cd /opt/hossein-hub && ./deploy.sh"

#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
chmod +x deploy.sh quick-deploy.sh setup-*.sh 2>/dev/null || true
docker compose up -d --build --remove-orphans archive-api document-intake-worker document-monitor-worker ocr-worker nginx
echo "QUICK DEPLOY OK"

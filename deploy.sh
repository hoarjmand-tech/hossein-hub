#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
chmod +x setup-connectors.sh enable-miniapp-public.sh setup-netops.sh setup-netops-credentials.sh setup-backup-timer.sh setup-google-drive-inbox.sh 2>/dev/null || true
docker compose -f docker-compose.yml up -d --build --remove-orphans
echo "DEPLOY OK"

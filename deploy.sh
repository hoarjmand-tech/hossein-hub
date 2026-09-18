#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
docker compose -f docker-compose.yml up -d --build --remove-orphans
echo "DEPLOY OK"

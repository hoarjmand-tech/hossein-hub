#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub

echo "===== CONTAINERS ====="
docker compose ps
echo "===== ARCHIVE HEALTH ====="
curl -fsS http://127.0.0.1:8080/health
echo
echo "===== SYSTEM STATUS ====="
curl -fsS http://127.0.0.1:8080/api/system/status
echo
echo "===== INBOX ====="
find scanner_inbox -maxdepth 1 -type f -printf '%f\n' | head -50
echo "===== DISK ====="
df -h /opt/hossein-hub
echo "===== RECENT LOGS ====="
docker compose logs --tail 30 archive document-intake telegram-bot

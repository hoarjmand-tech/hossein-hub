#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
cd "$ROOT"

git fetch origin main
git reset --hard origin/main
chmod +x setup-google-drive-inbox.sh quick-deploy.sh 2>/dev/null || true

echo "=== HOSSEIN HUB / GOOGLE DRIVE ONLY ==="
./setup-google-drive-inbox.sh

echo
echo "=== START DOCUMENT PIPELINE ==="
docker compose --profile drive up -d --build --remove-orphans archive-api document-intake-worker document-monitor-worker ocr-worker drive-sync nginx

echo
echo "=== HEALTH ==="
docker compose ps archive-api document-intake-worker document-monitor-worker ocr-worker drive-sync nginx
echo
echo "Google Drive folder: Hossein Hub Inbox"
echo "Folder ID: 1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP"
echo "GOOGLE-ONLY DOCUMENT PIPELINE READY"

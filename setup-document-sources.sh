#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
cd "$ROOT"

chmod +x setup-windows-i-inbox.sh setup-google-drive-inbox.sh quick-deploy.sh 2>/dev/null || true

echo "=== 1) Windows I:\HosseinHub-Inbox SMB ==="
if mountpoint -q /mnt/hossein-inbox; then
  echo "Windows I-drive inbox is already mounted."
else
  ./setup-windows-i-inbox.sh
fi

echo
echo "=== 2) Google Drive Hossein Hub Inbox ==="
./setup-google-drive-inbox.sh

echo
echo "=== 3) Document services ==="
docker compose --profile drive up -d document-intake-worker document-monitor-worker ocr-worker drive-sync archive-api nginx

echo
echo "=== STATUS ==="
docker compose ps archive-api document-intake-worker document-monitor-worker ocr-worker drive-sync nginx
echo "DOCUMENT SOURCES READY"

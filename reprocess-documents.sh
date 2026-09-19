#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
docker compose build --no-cache archive-api document-intake-worker ocr-worker
docker compose up -d --force-recreate archive-api document-intake-worker ocr-worker nginx
docker compose run --rm document-intake-worker python -m app.reprocess_documents
docker compose exec document-intake-worker tesseract --list-langs
echo "DOCUMENT REPROCESS OK"

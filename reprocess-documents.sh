#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
docker compose up -d --build --remove-orphans archive-api document-intake-worker ocr-worker
docker compose run --rm document-intake-worker python -m app.reprocess_documents
echo "DOCUMENT REPROCESS OK"

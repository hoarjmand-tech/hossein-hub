#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
git fetch origin main
git reset --hard origin/main
docker compose build --no-cache archive-api document-intake-worker ocr-worker
docker compose up -d --force-recreate archive-api document-intake-worker ocr-worker nginx
docker compose run --rm document-intake-worker python -m app.reprocess_documents
echo "=== REPROCESS SUMMARY ==="
docker compose exec -T postgres sh -c 'PGPASSWORD="$(cat /run/secrets/postgres_password)" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select coalesce(subtype,'(none)'),count(*) from documents where deleted=false group by subtype order by count(*) desc;"' || true
docker compose exec document-intake-worker tesseract --list-langs
echo "DOCUMENT REPROCESS OK"

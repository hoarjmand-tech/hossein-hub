#!/bin/bash
set -e

cd /opt/hossein-hub

echo "=== BACKUP ==="
cp archive_v2/main.py archive_v2/main.py.backup-smart-rename

echo "=== CHECK ==="
grep -q "document_analyzer" archive_v2/main.py || \
sed -i '1i from document_analyzer import analyze_document' archive_v2/main.py

echo "Patch prepared."
echo "Main.py backup created."
echo "Now rebuild container."

docker compose up -d --build

docker compose ps

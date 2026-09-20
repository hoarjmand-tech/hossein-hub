#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT/backups/ocr-$STAMP"
TEMP_DIR="$(mktemp -d /tmp/hossein-ocr-installer.XXXXXX)"

cleanup() {
  find "$TEMP_DIR" -mindepth 1 -delete 2>/dev/null || true
  rmdir "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if [[ ! -f "$PROJECT/docker-compose.yml" ]]; then
  echo "ERROR: $PROJECT/docker-compose.yml not found"
  exit 1
fi

payload_line="$(awk '/^__ARCHIVE_BELOW__$/ {print NR + 1; exit}' "$0")"
if [[ -z "$payload_line" ]]; then
  echo "ERROR: Embedded payload was not found"
  exit 1
fi

tail -n +"$payload_line" "$0" | base64 -d | tar -xzf - -C "$TEMP_DIR"

SOURCE="$TEMP_DIR/HosseinHub_OCR_Deploy"
required=(
  "$SOURCE/docker-compose.ocr.yml"
  "$SOURCE/ocr-worker/Dockerfile"
  "$SOURCE/ocr-worker/requirements.txt"
  "$SOURCE/ocr-worker/app/worker.py"
  "$SOURCE/ocr-worker/app/ocr_engine.py"
  "$SOURCE/ocr-worker/app/analyzer.py"
  "$SOURCE/ocr-worker/app/rename.py"
)

for file in "${required[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: Installer payload is incomplete: $file"
    exit 1
  fi
done

echo "===== BACKUP ====="
mkdir -p "$BACKUP"
[[ -d "$PROJECT/ocr-worker" ]] && cp -a "$PROJECT/ocr-worker" "$BACKUP/"
[[ -f "$PROJECT/docker-compose.ocr.yml" ]] && cp -a "$PROJECT/docker-compose.ocr.yml" "$BACKUP/"
echo "Backup: $BACKUP"

echo "===== INSTALL FILES ====="
mkdir -p "$PROJECT/ocr-worker"
cp -a "$SOURCE/ocr-worker/." "$PROJECT/ocr-worker/"
cp -a "$SOURCE/docker-compose.ocr.yml" "$PROJECT/docker-compose.ocr.yml"

echo "===== VALIDATE ====="
python3 -m py_compile "$PROJECT"/ocr-worker/app/*.py
cd "$PROJECT"
docker compose -f docker-compose.yml -f docker-compose.ocr.yml config --quiet

echo "===== BUILD ====="
docker compose -f docker-compose.yml -f docker-compose.ocr.yml build ocr-worker

echo "===== START ====="
docker compose -f docker-compose.yml -f docker-compose.ocr.yml up -d --no-deps ocr-worker

echo "===== HEALTH CHECK ====="
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8091/health >/tmp/hossein-ocr-health.json 2>/dev/null; then
    cat /tmp/hossein-ocr-health.json
    echo
    docker ps --filter name=hossein-hub-ocr-worker \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    echo "OCR DEPLOY COMPLETED SUCCESSFULLY"
    echo "Backup: $BACKUP"
    exit 0
  fi
  echo "Waiting for OCR service... $attempt/30"
  sleep 3
done

echo "ERROR: OCR health check failed"
docker logs --tail 200 hossein-hub-ocr-worker || true
echo "Backup: $BACKUP"
exit 1

__ARCHIVE_BELOW__
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
YQjxAFAAAA==

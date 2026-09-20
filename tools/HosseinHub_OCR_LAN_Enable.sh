#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
COMPOSE="$PROJECT/docker-compose.ocr.yml"
LAN_IP="192.168.1.35"
PORT="8091"
STAMP="$(date +%Y%m%d-%H%M%S)"

if ! ip -4 addr show | grep -Fq "${LAN_IP}/"; then
  echo "ERROR: ${LAN_IP} is not configured on this server."
  ip -4 -br addr show
  exit 1
fi

if [[ ! -f "$COMPOSE" ]]; then
  echo "ERROR: $COMPOSE not found. Deploy the OCR Worker first."
  exit 1
fi

cp -a "$COMPOSE" "${COMPOSE}.backup-${STAMP}"

python3 - "$COMPOSE" "$LAN_IP" "$PORT" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
ip = sys.argv[2]
port = sys.argv[3]
text = path.read_text(encoding="utf-8")

patterns = [
    r'127\.0\.0\.1:8091:8000',
    r'0\.0\.0\.0:8091:8000',
    r'192\.168\.1\.35:8091:8000',
]

replacement = f"{ip}:{port}:8000"
updated = text
for pattern in patterns:
    updated = re.sub(pattern, replacement, updated)

if replacement not in updated:
    raise SystemExit("ERROR: OCR port mapping was not found in docker-compose.ocr.yml")

path.write_text(updated, encoding="utf-8")
PY

cd "$PROJECT"

docker compose \
  -f docker-compose.yml \
  -f docker-compose.ocr.yml \
  config --quiet

docker compose \
  -f docker-compose.yml \
  -f docker-compose.ocr.yml \
  up -d --no-deps --force-recreate ocr-worker

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow from 192.168.1.0/24 to "$LAN_IP" port "$PORT" proto tcp \
    comment 'Hossein Hub OCR LAN'
fi

for attempt in $(seq 1 30); do
  if curl -fsS "http://${LAN_IP}:${PORT}/health" >/tmp/hossein-ocr-lan-health.json 2>/dev/null; then
    echo "===== HEALTH ====="
    cat /tmp/hossein-ocr-lan-health.json
    echo
    echo "===== LISTENING ====="
    ss -lntp | grep ":${PORT} " || true
    echo "===== CONTAINER ====="
    docker ps --filter name=hossein-hub-ocr-worker \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    echo "OCR LAN ACCESS ENABLED"
    echo "API Docs: http://${LAN_IP}:${PORT}/docs"
    exit 0
  fi
  sleep 3
done

echo "ERROR: OCR service did not become reachable on ${LAN_IP}:${PORT}."
docker logs --tail 150 hossein-hub-ocr-worker || true
exit 1

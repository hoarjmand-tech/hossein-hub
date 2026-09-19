#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
cd "$ROOT"

git fetch origin main
git reset --hard origin/main
mkdir -p "$ROOT/secrets"
chmod 700 "$ROOT/secrets"

TOKEN_FILE="$ROOT/secrets/drive_push_token"
if [ ! -s "$TOKEN_FILE" ]; then
  umask 077
  python3 - <<'PY' > "$TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(48))
PY
fi
chmod 600 "$TOKEN_FILE"

TOKEN="$(cat "$TOKEN_FILE")"
sed "s|__DRIVE_PUSH_TOKEN__|$TOKEN|g" google-drive-apps-script.template.gs > "$ROOT/google-drive-apps-script.gs"
chmod 600 "$ROOT/google-drive-apps-script.gs"

# rclone is no longer required for the Drive ingestion path.
if grep -q '^COMPOSE_PROFILES=' "$ROOT/.env" 2>/dev/null; then
  sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=/' "$ROOT/.env"
fi

docker compose up -d --build --remove-orphans archive-api document-intake-worker document-monitor-worker ocr-worker nginx

echo
echo "GOOGLE DRIVE PUSH PIPELINE READY"
echo "No rclone, no SSH tunnel, no Google Cloud OAuth client is required."
echo
echo "Next:"
echo "1) Open https://script.google.com in your browser"
echo "2) Create a New project"
echo "3) Copy the contents of:"
echo "   $ROOT/google-drive-apps-script.gs"
echo "4) Run installHosseinHubTrigger once and approve Google permissions"
echo
echo "After that, Hossein Hub Inbox is checked every 5 minutes automatically."

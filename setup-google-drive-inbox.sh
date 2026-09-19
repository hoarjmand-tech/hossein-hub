#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
DIR="$ROOT/secrets/rclone"
CONF="$DIR/rclone.conf"
FOLDER_ID="1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP"

sudo mkdir -p "$DIR"
sudo chown -R "$(id -un)":"$(id -gn)" "$DIR"
chmod 700 "$DIR"

echo "Google Drive one-time authorization\nTarget folder: Hossein Hub Inbox"
echo "Remote name must be: hossein-drive"
echo "When asked for storage type choose: Google Drive"
echo "Use your normal Google account OAuth login."
echo
docker run --rm -it   -v "$DIR:/config/rclone"   rclone/rclone:1.70.3 config --config /config/rclone/rclone.conf

if ! docker run --rm   -v "$DIR:/config/rclone:ro"   rclone/rclone:1.70.3 listremotes --config /config/rclone/rclone.conf | grep -qx 'hossein-drive:'; then
  echo "Remote 'hossein-drive' was not found. Run this script again and create it with that exact name."
  exit 2
fi

chmod 600 "$CONF"

if grep -q '^COMPOSE_PROFILES=' "$ROOT/.env"; then
  sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=drive/' "$ROOT/.env"
else
  printf '\nCOMPOSE_PROFILES=drive\n' >> "$ROOT/.env"
fi

cd "$ROOT"
docker compose --profile drive up -d drive-sync document-intake-worker
sleep 3
docker compose ps drive-sync document-intake-worker
echo
echo "GOOGLE DRIVE INBOX READY"
echo "Folder ID: $FOLDER_ID"
echo "New PDF/image files placed there will be synced and auto-archived."

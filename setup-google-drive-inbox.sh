#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
DIR="$ROOT/secrets/rclone"
CONF="$DIR/rclone.conf"
PASSFILE="$ROOT/secrets/rclone_config_pass"
FOLDER_ID="1aDh5o-paAS7HwFRnKBo2EUHYXe-LV8PP"

sudo mkdir -p "$DIR"
sudo chown -R "$(id -un)":"$(id -gn)" "$DIR"
chmod 700 "$DIR"
mkdir -p "$ROOT/secrets"

if [ ! -f "$PASSFILE" ]; then
  read -rsp "Rclone config password: " RCLONE_CONFIG_PASS; echo
  printf '%s' "$RCLONE_CONFIG_PASS" > "$PASSFILE"
  chmod 600 "$PASSFILE"
else
  RCLONE_CONFIG_PASS="$(cat "$PASSFILE")"
fi
export RCLONE_CONFIG_PASS

echo "Google Drive target: Hossein Hub Inbox"
echo "Folder ID: $FOLDER_ID"
echo

if docker run --rm -e RCLONE_CONFIG_PASS -v "$DIR:/config/rclone:ro" rclone/rclone:1.70.3 listremotes --config /config/rclone/rclone.conf 2>/dev/null | grep -qx 'hossein-drive:'; then
  echo "Existing hossein-drive remote found."
  echo "Attempting connection test..."
  if docker run --rm -e RCLONE_CONFIG_PASS -v "$DIR:/config/rclone:ro" rclone/rclone:1.70.3 lsf hossein-drive: --config /config/rclone/rclone.conf --drive-root-folder-id "$FOLDER_ID" >/dev/null 2>&1; then
    echo "Google Drive connection already valid."
  else
    echo "Remote exists but OAuth needs reconnect."
    docker run --rm -it --network host -e RCLONE_CONFIG_PASS -v "$DIR:/config/rclone" rclone/rclone:1.70.3 config reconnect hossein-drive: --config /config/rclone/rclone.conf
  fi
else
  echo "Creating hossein-drive remote."
  echo "Use remote name: hossein-drive"
  echo "Storage: Google Drive"
  echo "Client ID/Secret: leave blank unless using your own Google OAuth client"
  echo "Scope: 2"
  docker run --rm -it --network host -e RCLONE_CONFIG_PASS -v "$DIR:/config/rclone" rclone/rclone:1.70.3 config --config /config/rclone/rclone.conf
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
echo "New PDF/image files in Hossein Hub Inbox will sync every 5 minutes."

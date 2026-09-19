#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/hossein-hub
MOUNT=/mnt/hossein-inbox
CREDS="$ROOT/secrets/windows-inbox.credentials"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y cifs-utils

read -rp "Windows PC IP: " WIN_IP
read -rp "Windows username: " WIN_USER
read -rsp "Windows password: " WIN_PASS; echo

sudo mkdir -p "$MOUNT"
sudo mkdir -p "$ROOT/secrets"

cat > "$CREDS" <<EOF
username=$WIN_USER
password=$WIN_PASS
EOF
chmod 600 "$CREDS"

SHARE="//${WIN_IP}/HosseinHub-Inbox"
OPTS="credentials=$CREDS,vers=3.0,iocharset=utf8,noserverino,ro,_netdev"

sudo umount "$MOUNT" 2>/dev/null || true
sudo mount -t cifs "$SHARE" "$MOUNT" -o "$OPTS"

FSTAB_LINE="$SHARE $MOUNT cifs $OPTS 0 0"
if ! grep -Fq "$SHARE $MOUNT cifs" /etc/fstab; then
  echo "$FSTAB_LINE" | sudo tee -a /etc/fstab >/dev/null
fi

echo
echo "SMB MOUNT OK"
ls -la "$MOUNT" | head

cd "$ROOT"
docker compose up -d --force-recreate document-intake-worker
echo "WINDOWS I-DRIVE INBOX READY"

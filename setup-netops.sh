#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
DIR="$ROOT/secrets/netops"
INV="$DIR/devices.json"
sudo mkdir -p "$DIR"
sudo chown -R "$(id -un)":"$(id -gn)" "$DIR"
chmod 700 "$DIR"
[ -f "$INV" ] || printf '[]\n' > "$INV"

python3 "$ROOT/scripts/setup_netops.py" "$INV" "$DIR"
cd "$ROOT"
docker compose -f docker-compose.yml up -d --force-recreate archive-api netops-worker
echo "NETOPS SETUP OK"

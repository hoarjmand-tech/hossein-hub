#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
mkdir -p data/tailscale
docker compose -f docker-compose.yml up -d --force-recreate tailscale
echo "Waiting for Tailscale..."
STATE=$(docker exec hossein-hub-tailscale tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState",""))' 2>/dev/null || true)
if [ "$STATE" != "Running" ]; then
  echo "Tailscale is not authenticated in this container."
  echo "Run the login command shown by Tailscale once, approve it, then rerun this script."
  docker exec hossein-hub-tailscale tailscale up --hostname hossein-hub --accept-dns=false || true
  exit 2
fi
TSIP=$(docker exec hossein-hub-tailscale tailscale ip -4 | head -1)
DNS=$(docker exec hossein-hub-tailscale tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Self",{}).get("DNSName","").rstrip("."))')
echo "Tailscale connected: $TSIP"
docker exec hossein-hub-tailscale tailscale serve reset >/dev/null 2>&1 || true
docker exec hossein-hub-tailscale tailscale serve --bg --https=443 http://192.168.1.35:8080
echo
docker exec hossein-hub-tailscale tailscale serve status
echo
echo "HOSSEIN HUB HTTPS: https://$DNS"

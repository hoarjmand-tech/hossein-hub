#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
mkdir -p data/tailscale
docker compose -f docker-compose.yml up -d tailscale
echo "Checking Tailscale..."
if ! docker exec hossein-hub-tailscale tailscale ip -4 >/dev/null 2>&1; then
  docker exec -it hossein-hub-tailscale tailscale up --hostname hossein-hub --accept-dns=false
fi
TSIP=$(docker exec hossein-hub-tailscale tailscale ip -4 | head -1)
echo "Tailscale IP: $TSIP"
echo "Enabling private HTTPS proxy..."
docker exec hossein-hub-tailscale tailscale serve reset >/dev/null 2>&1 || true
docker exec hossein-hub-tailscale tailscale serve --bg --https=443 http://192.168.1.35:8080
echo
docker exec hossein-hub-tailscale tailscale serve status
echo
DNS=$(docker exec hossein-hub-tailscale tailscale status --json 2>/dev/null | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x.get("Self",{}).get("DNSName","").rstrip("."))' 2>/dev/null || true)
if [ -n "$DNS" ]; then echo "HOSSEIN HUB HTTPS: https://$DNS"; else echo "HTTPS enabled through Tailscale Serve."; fi

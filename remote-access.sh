#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
mkdir -p data/tailscale
docker compose -f docker-compose.yml up -d tailscale
echo
echo "Tailscale status:"
docker exec hossein-hub-tailscale tailscale status || true
echo
if ! docker exec hossein-hub-tailscale tailscale status 2>/dev/null | grep -q "hossein-hub"; then
 echo "If this is the first run, authenticate using the URL printed below:"
 docker exec -it hossein-hub-tailscale tailscale up --hostname hossein-hub --accept-dns=false
fi
echo
docker exec hossein-hub-tailscale tailscale ip -4 || true

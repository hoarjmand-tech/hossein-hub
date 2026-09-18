#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub

echo "[Mini App] enabling public HTTPS through Tailscale Funnel..."
if docker exec hossein-hub-tailscale tailscale funnel --bg --yes --https=443 http://127.0.0.1:8080; then
  echo
  docker exec hossein-hub-tailscale tailscale funnel status || true
  echo
  echo "MINI APP PUBLIC HTTPS ENABLED"
  echo "https://hossein-hub.tailf8fccb.ts.net/telegram"
else
  echo
  echo "FUNNEL_NOT_ENABLED"
  echo "Tailscale may require one-time approval for Funnel in the tailnet."
  exit 20
fi

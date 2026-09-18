#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
echo "== containers ==";docker compose -f docker-compose.yml ps
echo "== health ==";curl -fsS http://192.168.1.35:8080/health;echo
echo "== tailscale ==";docker exec hossein-hub-tailscale tailscale status || true
echo "== backups ==";systemctl is-active hossein-hub-backup.timer || true
echo "== disk ==";df -h /

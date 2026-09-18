#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
echo "== containers ==";docker compose -f docker-compose.yml ps
echo "== API ==";curl -fsS http://192.168.1.35:8080/health;echo
echo "== relay ==";systemctl is-active hossein-hub-telegram-relay || true;ss -lnt | grep "127.0.0.1:10808" || true
echo "== telegram ==";docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' hossein-hub-telegram 2>/dev/null || true
echo "== tailscale ==";docker exec hossein-hub-tailscale tailscale status || true
echo "== backups ==";systemctl is-active hossein-hub-backup.timer || true;ls -1dt backups/* 2>/dev/null|head -1||true
echo "== disk ==";df -h /

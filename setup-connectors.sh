#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
DIR="$ROOT/secrets/connectors"
mkdir -p "$DIR"
chmod 700 "$ROOT/secrets" "$DIR" 2>/dev/null || true
echo "Hossein Hub Connector Setup"
echo

read -rp "FortiGate host [192.168.1.10]: " FG_HOST
FG_HOST="${FG_HOST:-192.168.1.10}"
read -rp "FortiGate HTTPS port [9042]: " FG_PORT
FG_PORT="${FG_PORT:-9042}"
read -rsp "FortiGate API token (blank = keep current): " FG_TOKEN; echo
printf '{"host":"%s","port":%s,"scheme":"https","verify_tls":false}\n' "$FG_HOST" "$FG_PORT" > "$DIR/fortigate.json"
if [ -n "$FG_TOKEN" ]; then printf '%s' "$FG_TOKEN" > "$DIR/fortigate_token"; fi

echo
read -rp "ESXi/vCenter host (blank = skip): " ESXI_HOST
if [ -n "$ESXI_HOST" ]; then
  read -rp "ESXi/vCenter port [443]: " ESXI_PORT
  ESXI_PORT="${ESXI_PORT:-443}"
  read -rp "ESXi/vCenter username: " ESXI_USER
  read -rsp "ESXi/vCenter password: " ESXI_PASS; echo
  printf '{"host":"%s","port":%s,"verify_tls":false}\n' "$ESXI_HOST" "$ESXI_PORT" > "$DIR/esxi.json"
  printf '%s' "$ESXI_USER" > "$DIR/esxi_user"
  printf '%s' "$ESXI_PASS" > "$DIR/esxi_password"
fi

echo
read -rp "Veeam server host (blank = skip): " VEEAM_HOST
if [ -n "$VEEAM_HOST" ]; then
  read -rp "Veeam REST port [9419]: " VEEAM_PORT
  VEEAM_PORT="${VEEAM_PORT:-9419}"
  read -rp "Veeam username: " VEEAM_USER
  read -rsp "Veeam password: " VEEAM_PASS; echo
  printf '{"host":"%s","port":%s,"scheme":"https","api_version":"1.2-rev1","verify_tls":false}\n' "$VEEAM_HOST" "$VEEAM_PORT" > "$DIR/veeam.json"
  printf '%s' "$VEEAM_USER" > "$DIR/veeam_user"
  printf '%s' "$VEEAM_PASS" > "$DIR/veeam_password"
fi

chmod 600 "$DIR"/* 2>/dev/null || true
unset FG_TOKEN ESXI_PASS VEEAM_PASS
echo
echo "Connector secrets saved locally."
cd "$ROOT"
docker compose -f docker-compose.yml up -d --force-recreate archive-api
echo "CONNECTOR SETUP OK"

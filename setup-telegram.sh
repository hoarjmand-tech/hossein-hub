#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
TOKEN="${1:-}"
USERS="${2:-}"
MINI_URL="${3:-}"
CLOUDFLARE_TOKEN="${4:-}"

if [[ -z "$TOKEN" ]]; then
  read -rsp "Telegram Bot Token: " TOKEN
  echo
fi
[[ -n "$TOKEN" ]] || { echo "Bot token is required."; exit 1; }

if [[ -z "$USERS" ]]; then
  read -rp "Allowed Telegram User ID(s), comma-separated [keep current]: " USERS
fi
if [[ -z "$MINI_URL" ]]; then
  read -rp "Public HTTPS Mini App URL [keep current]: " MINI_URL
fi
if [[ -n "$MINI_URL" && "$MINI_URL" != https://* ]]; then
  echo "Mini App URL must start with https://"
  exit 1
fi
if [[ -z "$CLOUDFLARE_TOKEN" ]]; then
  read -rsp "Cloudflare Tunnel Token [keep current / optional]: " CLOUDFLARE_TOKEN
  echo
fi

cd "$PROJECT"
[[ -f .env ]] || cp .env.example .env

python3 - "$PROJECT/.env" "$TOKEN" "$USERS" "$MINI_URL" "$CLOUDFLARE_TOKEN" <<'PY'
import sys
from pathlib import Path

path=Path(sys.argv[1])
values={
    "TELEGRAM_BOT_TOKEN":sys.argv[2],
}
if sys.argv[3]:
    values["TELEGRAM_ALLOWED_USERS"]=sys.argv[3]
if sys.argv[4]:
    values["TELEGRAM_MINI_APP_URL"]=sys.argv[4]
    values["PUBLIC_BASE_URL"]=sys.argv[4].removesuffix("/telegram").rstrip("/")
if sys.argv[5]:
    values["CLOUDFLARE_TUNNEL_TOKEN"]=sys.argv[5]
lines=path.read_text(encoding="utf-8").splitlines() if path.exists() else []
seen=set();out=[]
for line in lines:
    key=line.split("=",1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in values:
        out.append(f"{key}={values[key]}");seen.add(key)
    else:
        out.append(line)
for key,value in values.items():
    if key not in seen:out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip()+"\n",encoding="utf-8")
PY

chmod 600 .env
if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.' .env; then
  docker compose --profile cloudflare up -d --force-recreate archive telegram-gateway telegram-bot cloudflared
else
  docker compose up -d --force-recreate archive telegram-gateway telegram-bot
fi
echo "Telegram module configured."
docker compose logs --tail 30 telegram-bot

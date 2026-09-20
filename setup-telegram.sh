#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/opt/hossein-hub"
TOKEN="${1:-}"
USERS="${2:-}"

if [[ -z "$TOKEN" ]]; then
  echo "Usage: sudo bash setup-telegram.sh BOT_TOKEN [TELEGRAM_USER_ID[,ID...]]"
  exit 1
fi

cd "$PROJECT"
[[ -f .env ]] || cp .env.example .env

python3 - "$PROJECT/.env" "$TOKEN" "$USERS" <<'PY'
import sys
from pathlib import Path

path=Path(sys.argv[1])
values={"TELEGRAM_BOT_TOKEN":sys.argv[2],"TELEGRAM_ALLOWED_USERS":sys.argv[3]}
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
docker compose up -d --force-recreate telegram-bot archive
echo "Telegram module configured."
docker compose logs --tail 30 telegram-bot

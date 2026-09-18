#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
DIR="$ROOT/secrets/netops"
sudo mkdir -p "$DIR"
sudo chown -R "$(id -un)":"$(id -gn)" "$DIR"
chmod 700 "$DIR"

read -rp "Credential profile name [network-admin]: " PROFILE
PROFILE="${PROFILE:-network-admin}"
read -rp "Username: " USERNAME
read -rsp "Password: " PASSWORD; echo
read -rsp "Enable secret (blank if none): " ENABLE; echo

printf '%s' "$USERNAME" > "$DIR/profile-$PROFILE.user"
printf '%s' "$PASSWORD" > "$DIR/profile-$PROFILE.password"
if [ -n "$ENABLE" ]; then printf '%s' "$ENABLE" > "$DIR/profile-$PROFILE.enable"; fi
chmod 600 "$DIR"/profile-"$PROFILE".*

python3 - "$DIR/devices.json" "$PROFILE" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);profile=sys.argv[2]
try:d=json.loads(p.read_text())
except:d=[]
for x in d:
    if x.get("enabled", True) and not x.get("username_file"):
        x["username_file"]=f"profile-{profile}.user"
        x["password_file"]=f"profile-{profile}.password"
        ep=Path(p.parent/f"profile-{profile}.enable")
        if ep.exists():x["enable_secret_file"]=ep.name
p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
print("Profile assigned to enabled devices without credentials.")
PY

cd "$ROOT"
docker compose -f docker-compose.yml up -d --force-recreate archive-api netops-worker
echo "NETOPS CREDENTIAL PROFILE OK"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/hossein-hub
WG_DIR="$ROOT/secrets/wireguard"
WG_IF=wg0
WG_NET="10.77.77.0/24"
WG_SERVER="10.77.77.1/24"
WG_CLIENT="10.77.77.2/32"
WG_PORT="51820"
PUBLIC_ENDPOINT="95.38.99.146:$WG_PORT"

LAN_IF="$(ip route get 192.168.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
[ -n "$LAN_IF" ] || LAN_IF="$(ip route | awk '/default/ {print $5; exit}')"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard qrencode

sudo mkdir -p /etc/wireguard "$WG_DIR"
sudo chown -R "$(id -un)":"$(id -gn)" "$WG_DIR"
chmod 700 "$WG_DIR"

if [ ! -f "$WG_DIR/server_private.key" ]; then
  umask 077
  wg genkey | tee "$WG_DIR/server_private.key" | wg pubkey > "$WG_DIR/server_public.key"
fi
if [ ! -f "$WG_DIR/iphone_private.key" ]; then
  umask 077
  wg genkey | tee "$WG_DIR/iphone_private.key" | wg pubkey > "$WG_DIR/iphone_public.key"
fi

SERVER_PRIV="$(cat "$WG_DIR/server_private.key")"
SERVER_PUB="$(cat "$WG_DIR/server_public.key")"
CLIENT_PRIV="$(cat "$WG_DIR/iphone_private.key")"
CLIENT_PUB="$(cat "$WG_DIR/iphone_public.key")"

sudo tee /etc/wireguard/${WG_IF}.conf >/dev/null <<EOF
[Interface]
Address = ${WG_SERVER}
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}
PostUp = iptables -A FORWARD -i ${WG_IF} -j ACCEPT; iptables -A FORWARD -o ${WG_IF} -j ACCEPT; iptables -t nat -A POSTROUTING -s ${WG_NET} -o ${LAN_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i ${WG_IF} -j ACCEPT; iptables -D FORWARD -o ${WG_IF} -j ACCEPT; iptables -t nat -D POSTROUTING -s ${WG_NET} -o ${LAN_IF} -j MASQUERADE

[Peer]
PublicKey = ${CLIENT_PUB}
AllowedIPs = ${WG_CLIENT}
EOF

sudo chmod 600 /etc/wireguard/${WG_IF}.conf
sudo tee /etc/sysctl.d/99-hossein-hub-wireguard.conf >/dev/null <<EOF
net.ipv4.ip_forward=1
EOF
sudo sysctl --system >/dev/null

cat > "$WG_DIR/iphone.conf" <<EOF
[Interface]
PrivateKey = ${CLIENT_PRIV}
Address = ${WG_CLIENT}
DNS = 192.168.1.1

[Peer]
PublicKey = ${SERVER_PUB}
Endpoint = ${PUBLIC_ENDPOINT}
AllowedIPs = 192.168.1.0/24, 192.168.22.0/24, 10.77.77.0/24
PersistentKeepalive = 25
EOF
chmod 600 "$WG_DIR/iphone.conf"

if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow ${WG_PORT}/udp
fi

sudo systemctl enable wg-quick@${WG_IF}
sudo systemctl restart wg-quick@${WG_IF}

echo
echo "WIREGUARD SERVER READY"
echo "Server LAN IP: 192.168.1.35"
echo "WireGuard UDP port: ${WG_PORT}"
echo "Public endpoint expected: ${PUBLIC_ENDPOINT}"
echo
echo "Create FortiGate VIP/Port Forward:"
echo "WAN1 UDP ${WG_PORT} -> 192.168.1.35 UDP ${WG_PORT}"
echo
echo "iPhone client QR:"
qrencode -t ansiutf8 < "$WG_DIR/iphone.conf"
echo
echo "Client config stored securely at:"
echo "$WG_DIR/iphone.conf"
echo
echo "After iPhone WireGuard connects, SSH to: 192.168.1.35 port 22"

#!/bin/bash

set -e

BASE="/opt/hossein-hub/agent"

echo "Installing Hossein Agent..."

python3 -m pip install -r $BASE/requirements.txt

chmod +x $BASE/agent.py

cat >/etc/systemd/system/hossein-agent.service <<SERVICE
[Unit]
Description=Hossein Hub Management Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$BASE
ExecStart=/usr/bin/python3 $BASE/agent.py
Restart=always
RestartSec=5
User=hossein

[Install]
WantedBy=multi-user.target
SERVICE


systemctl daemon-reload
systemctl enable hossein-agent
systemctl restart hossein-agent

echo "=== STATUS ==="
systemctl status hossein-agent --no-pager

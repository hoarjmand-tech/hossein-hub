#!/bin/bash

set -e

BASE="/opt/hossein-hub/agent"

pip3 install -r $BASE/requirements.txt

cat >/etc/systemd/system/hossein-agent.service <<SERVICE
[Unit]
Description=Hossein Hub Agent
After=network.target

[Service]
WorkingDirectory=$BASE
ExecStart=/usr/bin/python3 $BASE/agent.py
Restart=always
User=hossein

[Install]
WantedBy=multi-user.target
SERVICE


systemctl daemon-reload
systemctl enable hossein-agent
systemctl restart hossein-agent

systemctl status hossein-agent --no-pager

#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/hossein-hub
sudo tee /etc/systemd/system/hossein-hub-backup.service >/dev/null <<'EOF'
[Unit]
Description=Hossein Hub encrypted backup
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/hossein-hub
ExecStart=/usr/bin/bash /opt/hossein-hub/backup.sh
User=root
EOF

sudo tee /etc/systemd/system/hossein-hub-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Daily Hossein Hub encrypted backup

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300
Unit=hossein-hub-backup.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hossein-hub-backup.timer
sudo systemctl list-timers hossein-hub-backup.timer --no-pager
echo "HOST BACKUP TIMER OK"

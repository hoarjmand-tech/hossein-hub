#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/hossein-hub
sudo install -m 0644 systemd/hossein-hub-backup.service /etc/systemd/system/
sudo install -m 0644 systemd/hossein-hub-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hossein-hub-backup.timer
systemctl list-timers hossein-hub-backup.timer --no-pager

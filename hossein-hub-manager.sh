#!/bin/bash
set -e

APP="/opt/hossein-hub"

echo "================================"
echo " Hossein Hub Manager"
echo "================================"

cd "$APP"

case "$1" in

status)
    docker compose ps
    ;;

logs)
    docker compose logs --tail=100 archive
    ;;

restart)
    docker compose restart
    ;;

build)
    docker compose up -d --build
    ;;

backup)
    mkdir -p backups/manual
    tar czf backups/manual/backup-$(date +%Y%m%d-%H%M%S).tar.gz archive_v2 archive_data docker-compose.yml
    echo "Backup completed"
    ;;

check)
    echo "=== Containers ==="
    docker compose ps
    echo
    echo "=== Disk ==="
    df -h /
    echo
    echo "=== Docker ==="
    docker system df
    ;;

*)
    echo "Usage:"
    echo "$0 status"
    echo "$0 logs"
    echo "$0 restart"
    echo "$0 build"
    echo "$0 backup"
    echo "$0 check"
    exit 1
    ;;

esac

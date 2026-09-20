#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import json
import yaml
import os
from datetime import datetime
from pathlib import Path


BASE = Path("/opt/hossein-hub/agent")

CONFIG = yaml.safe_load(
    open(BASE / "config.yaml")
)

ALLOWED = yaml.safe_load(
    open(BASE / "allowed_tasks.yaml")
)["allowed"]

LOG = BASE / "agent.log"


def log(msg):
    with open(LOG, "a") as f:
        f.write(
            f"{datetime.now()} {msg}\n"
        )


def run(cmd):
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )

        return {
            "code": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr
        }

    except Exception as e:
        return {
            "error": str(e)
        }


def execute(task):

    if task == "status":
        return run(
            "cd /opt/hossein-hub && docker compose ps"
        )

    if task == "docker_status":
        return run(
            "docker ps"
        )

    if task == "docker_logs":
        return run(
            "cd /opt/hossein-hub && docker compose logs --tail=100 archive"
        )

    if task == "docker_restart":
        return run(
            "cd /opt/hossein-hub && docker compose restart"
        )

    if task == "backup":
        return run(
            "cd /opt/hossein-hub && ./hossein-hub-manager.sh backup"
        )

    if task == "disk_check":
        return run(
            "df -h"
        )

    if task == "health":
        return run(
            "curl -s http://localhost:8080/health"
        )

    return {
        "error":"Unknown task"
    }


class Handler(BaseHTTPRequestHandler):

    def do_POST(self):

        token = self.headers.get(
            "X-Agent-Token"
        )

        if token != CONFIG["token"]:
            self.send_response(403)
            self.end_headers()
            return


        length = int(
            self.headers["Content-Length"]
        )

        body = self.rfile.read(length)

        data = json.loads(body)

        task = data.get("task")


        if task not in ALLOWED:
            self.send_response(400)
            self.end_headers()
            return


        log(task)

        result = execute(task)


        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.end_headers()

        self.wfile.write(
            json.dumps(result).encode()
        )


server = HTTPServer(
    (
        CONFIG["bind"],
        CONFIG["port"]
    ),
    Handler
)

print(
    "Hossein Agent started"
)

server.serve_forever()

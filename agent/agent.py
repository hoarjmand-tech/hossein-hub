#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import json
import yaml
import os
import shlex
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


def execute(task, parameters=None):
    parameters = parameters or {}

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

    if task in ("fortigate_status", "network_snapshot", "fortigate_report", "fortigate_change"):
        # Hermes/NetOps uses the existing Ansible SSH read-only workflow.
        # The agent never accepts an arbitrary command from the web UI.
        root = Path(os.getenv("NETOPS_ROOT", "/opt/ansible/netops"))
        if not root.is_dir():
            return {"error": f"NETOPS_ROOT not found: {root}"}
        if task == "fortigate_status":
            candidates = [root / "playbooks/fortigate-ssh-check.yml", root / "playbooks/fortigate_status.yml"]
        elif task == "fortigate_report":
            candidates = [root / "playbooks/fortigate-report.yml", root / "playbooks/fortigate_report.yml", root / "playbooks/fortigate-ssh-check.yml"]
        elif task == "fortigate_change":
            operation = str(parameters.get("operation") or "")
            if operation not in {"set_dns", "set_hostname", "create_address", "disable_policy", "enable_policy"}:
                return {"error": "عملیات تغییر FortiGate مجاز نیست"}
            candidates = [root / "playbooks/fortigate-change.yml", root / "playbooks/fortigate_change.yml"]
        else:
            candidates = [root / "playbooks/network-snapshot.yml", root / "playbooks/network_snapshot.yml", root / "playbooks/fortigate-ssh-check.yml"]
        playbook = next((p for p in candidates if p.is_file()), None)
        if not playbook:
            return {"error": "هیچ playbook مجاز NetOps برای این عملیات پیدا نشد"}
        vault_file = os.getenv("ANSIBLE_VAULT_PASSWORD_FILE", str(root / ".vault_pass"))
        if not Path(vault_file).is_file():
            return {"error": "ANSIBLE_VAULT_PASSWORD_FILE تنظیم نشده یا فایل رمز Vault وجود ندارد"}
        extra = ""
        if task == "fortigate_report":
            extra = " -e " + shlex.quote("report_kind=" + str(parameters.get("kind") or "status"))
        elif task == "fortigate_change":
            extra = " -e " + shlex.quote("operation=" + str(parameters.get("operation")))
            extra += " -e " + shlex.quote("values_json=" + json.dumps(parameters.get("values") or {}, ensure_ascii=False))
        cmd = f"cd {shlex.quote(str(root))} && ansible-playbook {shlex.quote(str(playbook))} --vault-password-file {shlex.quote(vault_file)}{extra}"
        return run(cmd)

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
        parameters = data.get("parameters") or {}


        if task not in ALLOWED:
            self.send_response(400)
            self.end_headers()
            return


        log(task)

        result = execute(task, parameters)


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

import json, sys, getpass
from pathlib import Path

invp = Path(sys.argv[1])
root = Path(sys.argv[2])

try:
    devices = json.loads(invp.read_text())
    if not isinstance(devices, list):
        devices = []
except Exception:
    devices = []

print("Hossein Hub NetOps device setup")
print("Device types: cisco_ios, cisco_nxos, fortinet, mikrotik_routeros, arista_eos, juniper_junos, linux")

while True:
    name = input("Device name (blank = finish): ").strip()
    if not name:
        break
    did = input("Device ID [auto]: ").strip() or name.lower().replace(" ", "-")
    host = input("Host/IP: ").strip()
    dtype = input("Netmiko device_type [cisco_ios]: ").strip() or "cisco_ios"
    port = int(input("SSH port [22]: ").strip() or "22")
    user = input("Username: ").strip()
    pwd = getpass.getpass("Password: ")
    ena = getpass.getpass("Enable secret (blank if none): ")
    site = input("Site [HQ]: ").strip() or "HQ"
    role = input("Role [network]: ").strip() or "network"

    uf = did + ".user"
    pf = did + ".password"
    ef = did + ".enable"
    (root / uf).write_text(user)
    (root / pf).write_text(pwd)
    if ena:
        (root / ef).write_text(ena)

    d = {
        "id": did, "name": name, "host": host, "port": port,
        "device_type": dtype, "site": site, "role": role, "enabled": True,
        "username_file": uf, "password_file": pf
    }
    if ena:
        d["enable_secret_file"] = ef
    devices = [x for x in devices if str(x.get("id")) != did]
    devices.append(d)

invp.write_text(json.dumps(devices, ensure_ascii=False, indent=2))
for p in root.iterdir():
    if p.is_file():
        p.chmod(0o600)
print("Saved %d device(s)." % len(devices))

#!/usr/bin/env bash
# Reads /etc/opple-bridge/wifi.yaml and configures NetworkManager connections.
# Run as a systemd oneshot service at boot.
set -euo pipefail

CONFIG="/etc/opple-bridge/wifi.yaml"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/../../venv/bin/python"

if [ ! -f "$CONFIG" ]; then
    echo "wifi-bootstrap: $CONFIG not found, skipping"
    exit 0
fi

"$PYTHON" - "$CONFIG" <<'PYEOF'
import sys
import subprocess
import yaml

config_path = sys.argv[1]
with open(config_path) as f:
    data = yaml.safe_load(f)

for net in data.get("networks", []):
    ssid = net["ssid"]
    psk = net.get("psk")
    priority = net.get("priority", 50)
    # Create or update connection
    cmd = [
        "nmcli", "connection", "add", "type", "wifi",
        "ifname", "wlan0",
        "con-name", f"opple-{ssid}",
        "ssid", ssid,
        "connection.autoconnect-priority", str(priority),
        "connection.autoconnect", "yes",
    ]
    if psk:
        cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk]
    # Modify if exists, otherwise add
    exists = subprocess.run(
        ["nmcli", "connection", "show", f"opple-{ssid}"],
        capture_output=True
    ).returncode == 0
    if exists:
        mod_cmd = ["nmcli", "connection", "modify", f"opple-{ssid}",
                   "connection.autoconnect", "yes",
                   "connection.autoconnect-priority", str(priority)]
        if psk:
            mod_cmd += ["wifi-sec.psk", psk]
        subprocess.run(mod_cmd, check=True)
        print(f"Updated: {ssid}")
    else:
        subprocess.run(cmd, check=True)
        print(f"Added: {ssid} (priority {priority})")

print("WiFi bootstrap complete")
PYEOF

#!/usr/bin/env bash
# Waits for WiFi connectivity after boot; if none within MAX_WAIT seconds,
# activates an nmcli hotspot. Run as a systemd oneshot service (root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/../../venv/bin/python"
CONFIG_FILE="/etc/opple-bridge/wifi.yaml"
MAX_WAIT=45
CHECK_INTERVAL=3
HOTSPOT_CON="opple-hotspot"

# --- Idempotence: already in AP mode → nothing to do ---
if nmcli -t -f GENERAL.STATE device show wlan0 2>/dev/null | grep -qi "local.only"; then
    echo "hotspot-fallback: wlan0 already in AP mode, exiting"
    exit 0
fi

# --- Wait for connectivity ---
echo "hotspot-fallback: waiting up to ${MAX_WAIT}s for WiFi connectivity"
elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    state=$(nmcli -t -f CONNECTIVITY general 2>/dev/null || true)
    if [ "$state" = "full" ]; then
        echo "hotspot-fallback: connectivity=full after ${elapsed}s, no hotspot needed"
        exit 0
    fi
    sleep "$CHECK_INTERVAL"
    elapsed=$((elapsed + CHECK_INTERVAL))
done

echo "hotspot-fallback: no connectivity after ${MAX_WAIT}s, activating hotspot"

# --- Read hotspot config from wifi.yaml (with defaults) ---
SSID="OPPLE BRIDGE"
PSK="opple-bridge"
IP="192.168.1.1"

if [ -f "$CONFIG_FILE" ]; then
    result=$("$PYTHON" - "$CONFIG_FILE" <<'PYEOF'
import sys
import yaml

config_path = sys.argv[1]
try:
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    hotspot = data.get("hotspot") or {}
    ssid = hotspot.get("ssid") or "OPPLE BRIDGE"
    psk_key = "psk"
    if psk_key in hotspot and hotspot[psk_key] is None:
        psk = ""
    else:
        psk = hotspot.get("psk") or "opple-bridge"
    ip = hotspot.get("ip") or "192.168.1.1"
    timeout = int(hotspot.get("fallback_after_s", data.get("fallback_after_s", 45)))
    print(ssid)
    print(psk)
    print(ip)
    print(timeout)
except Exception:
    print("OPPLE BRIDGE")
    print("opple-bridge")
    print("192.168.1.1")
    print(45)
PYEOF
)
    SSID=$(echo "$result" | sed -n '1p')
    PSK=$(echo "$result" | sed -n '2p')
    IP=$(echo "$result" | sed -n '3p')
    YAML_TIMEOUT=$(echo "$result" | sed -n '4p')
    [ -z "$IP" ] && IP="192.168.1.1"
    if [ -n "$YAML_TIMEOUT" ] && [ "$YAML_TIMEOUT" -eq "$YAML_TIMEOUT" ] 2>/dev/null; then
        MAX_WAIT="$YAML_TIMEOUT"
    fi
fi

echo "hotspot-fallback: SSID='${SSID}' IP=${IP}"

# --- Activate hotspot with explicit IP ---
nmcli device disconnect wlan0 2>/dev/null || true
nmcli connection delete "$HOTSPOT_CON" 2>/dev/null || true

HOTSPOT_ARGS=(
    connection add type wifi ifname wlan0 con-name "$HOTSPOT_CON"
    ssid "$SSID"
    802-11-wireless.mode ap
    802-11-wireless.band bg
    ipv4.method shared
    ipv4.addresses "${IP}/24"
)
if [ -n "$PSK" ]; then
    HOTSPOT_ARGS+=(wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK")
fi
nmcli "${HOTSPOT_ARGS[@]}"
nmcli connection up "$HOTSPOT_CON" ifname wlan0
echo "hotspot-fallback: hotspot active at ${IP}"

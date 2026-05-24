#!/usr/bin/env bash
# Idempotent setup script for Opple Bridge on Raspberry Pi Zero 2W (Bookworm).
# Run as root: sudo bash provision.sh
# Safe to re-run after updates.
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
    echo "Run as root via sudo: sudo bash raspberry/scripts/provision.sh"
    exit 1
fi

if [ -z "${SUDO_USER:-}" ]; then
    echo "Run this from your normal login user with sudo, not from a root shell."
    echo "Example: ssh <your-user>@<pi-host> then sudo bash raspberry/scripts/provision.sh"
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$REPO_DIR/venv"
UNIT_DIR="/etc/systemd/system"
CONFIG_DIR="/etc/opple-bridge"
PI_USER="${SUDO_USER}"

if ! id "$PI_USER" >/dev/null 2>&1; then
    echo "User '$PI_USER' does not exist on this system."
    exit 1
fi

echo "=== Opple Bridge provisioning ==="
echo "Repo: $REPO_DIR"
echo "User: $PI_USER"
echo ""

# 1. Install system packages
echo "--- Installing packages ---"
apt-get update -q
apt-get install -y -q \
    python3-venv python3-pip \
    avahi-daemon \
    network-manager \
    bluetooth bluez

# log2ram — not in standard repos, install from azlux repo
if ! command -v log2ram &>/dev/null; then
    echo "--- Installing log2ram ---"
    curl -fsSL https://azlux.fr/repo.gpg \
        -o /usr/share/keyrings/azlux-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/azlux-archive-keyring.gpg] http://packages.azlux.fr/debian/ bookworm main" \
        > /etc/apt/sources.list.d/azlux.list
    apt-get update -q
    apt-get install -y -q log2ram
else
    echo "--- log2ram already installed ---"
fi

# 2. Switch from dhcpcd/wpa_supplicant to NetworkManager
echo "--- Configuring NetworkManager ---"
systemctl disable dhcpcd wpa_supplicant 2>/dev/null || true
systemctl enable NetworkManager
systemctl start NetworkManager 2>/dev/null || true
# Tell NetworkManager to manage wlan0
if ! grep -q "managed=true" /etc/NetworkManager/NetworkManager.conf 2>/dev/null; then
    cat >> /etc/NetworkManager/NetworkManager.conf <<'EOF'
[ifupdown]
managed=true
EOF
fi

# Remove all existing WiFi connections so first boot always starts with hotspot.
# This clears any pre-configured connections from the Pi OS image.
echo "--- Removing pre-existing WiFi connections ---"
nmcli -t -f NAME,TYPE connection show 2>/dev/null \
    | grep ':802-11-wireless$' \
    | cut -d: -f1 \
    | while IFS= read -r con; do
        nmcli connection delete "$con" && echo "  Deleted: $con" || true
    done

# 3. Install PiSugar server (official installer)
# The installer uses dpkg-reconfigure which requires an interactive terminal to
# select the model — it silently leaves --model '' when run non-interactively.
# We patch both defaults files afterward to set the model explicitly.
if ! systemctl is-active --quiet pisugar-server 2>/dev/null; then
    echo "--- Installing PiSugar server ---"
    curl -s https://cdn.pisugar.com/release/pisugar-power-manager.sh | bash
else
    echo "--- PiSugar server already installed ---"
fi
echo "--- Configuring PiSugar model ---"
sed -i "s/--model ''/--model 'PiSugar 3'/" /etc/default/pisugar-server
sed -i "s/--model ''/--model 'PiSugar 3'/" /etc/default/pisugar-poweroff
systemctl restart pisugar-server

# 4. Create virtualenv and install dependencies
echo "--- Setting up Python environment ---"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO_DIR/requirements-pi.txt"

# Waveshare e-paper library — not on PyPI, install via sparse clone into venv site-packages
echo "--- Installing Waveshare EPD library ---"
apt-get install -y -q python3-rpi.gpio python3-spidev python3-lgpio
"$VENV/bin/pip" install -q RPi.GPIO spidev lgpio
SITE_PKG=$("$VENV/bin/python" -c "import site; print(site.getsitepackages()[0])")
if [ ! -d "$SITE_PKG/waveshare_epd" ]; then
    TMP=$(mktemp -d)
    git clone --depth=1 --filter=blob:none --sparse https://github.com/waveshare/e-Paper.git "$TMP" 2>&1
    cd "$TMP"
    git sparse-checkout set RaspberryPi_JetsonNano/python/lib/waveshare_epd
    cp -r RaspberryPi_JetsonNano/python/lib/waveshare_epd "$SITE_PKG/"
    cd "$REPO_DIR"
    rm -rf "$TMP"
else
    echo "waveshare_epd already installed"
fi

# 5. Enable SPI (needed for Waveshare e-paper)
echo "--- Enabling SPI ---"
raspi-config nonint do_spi 0

# 6. Enable hardware watchdog
echo "--- Enabling hardware watchdog ---"
if ! grep -q "dtparam=watchdog=on" /boot/firmware/config.txt; then
    echo "dtparam=watchdog=on" >> /boot/firmware/config.txt
fi
if ! grep -q "RuntimeWatchdogSec" /etc/systemd/system.conf; then
    echo "RuntimeWatchdogSec=15" >> /etc/systemd/system.conf
fi

# 7. Install systemd units (substitute __USER__ and __REPO_DIR__ placeholders)
echo "--- Installing systemd units ---"
for svc in "$REPO_DIR/raspberry/systemd/"*.service; do
    dest="$UNIT_DIR/$(basename "$svc")"
    sed -e "s|__USER__|$PI_USER|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$svc" > "$dest"
done
systemctl daemon-reload
systemctl enable opple-bridge.service opple-pi.service opple-bridge-wifi-bootstrap.service opple-bridge-hotspot-fallback.service

# 8. Create config directory and copy examples if not present
echo "--- Setting up config ---"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/wifi.yaml" ]; then
    cp "$REPO_DIR/raspberry/config/wifi.yaml.example" "$CONFIG_DIR/wifi.yaml"
    echo "NOTE: Edit $CONFIG_DIR/wifi.yaml with your network credentials"
fi

chown "root:${PI_USER}" "${CONFIG_DIR}"
chmod 775 "${CONFIG_DIR}"
if [ -f "${CONFIG_DIR}/wifi.yaml" ]; then
    chown "root:${PI_USER}" "${CONFIG_DIR}/wifi.yaml"
    chmod 664 "${CONFIG_DIR}/wifi.yaml"
fi

# Polkit rule — allow PI_USER to manage NetworkManager connections
mkdir -p /etc/polkit-1/localauthority/50-local.d
cat > /etc/polkit-1/localauthority/50-local.d/50-opple-bridge-nm.pkla << POLKIT
[Opple Bridge - NetworkManager]
Identity=unix-user:${PI_USER}
Action=org.freedesktop.NetworkManager.*;org.freedesktop.NetworkManager.settings.modify.system;org.freedesktop.NetworkManager.wifi.share.open
ResultAny=yes
ResultInactive=yes
ResultActive=yes
POLKIT

# Sudoers — allow PI_USER to reboot/shutdown without password
echo "${PI_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff" \
    > /tmp/opple-bridge-sudoers
chmod 440 /tmp/opple-bridge-sudoers
visudo -cf /tmp/opple-bridge-sudoers && mv /tmp/opple-bridge-sudoers /etc/sudoers.d/opple-bridge

# 9. log2ram config — reduce SD writes
if [ -f /etc/log2ram.conf ]; then
    sed -i 's/SIZE=.*/SIZE=64M/' /etc/log2ram.conf
fi

# 10. Fix journald size
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/opple.conf <<'EOF'
[Journal]
SystemMaxUse=50M
EOF

echo ""
echo "=== Provisioning complete ==="
echo ""
echo "The Pi will reboot in 5 seconds."
echo "It will start in hotspot mode (SSID: OPPLE BRIDGE)."
echo "Connect to it and open http://192.168.1.1 to add your WiFi networks."
echo ""
sleep 5
reboot

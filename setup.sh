#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sports Ticker — Pi Setup Script
# Run once on a fresh Raspberry Pi:  sudo bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_URL="https://github.com/MattLD13/SportsTickerBackend.git"
INSTALL_DIR="/home/mld"
PROJECT_DIR="$INSTALL_DIR"   # repo cloned directly into home dir (matches deploy)
SERVICE_SRC="$PROJECT_DIR/ticker-controller.service"
SERVICE_DST="/etc/systemd/system/ticker-controller.service"
PYTHON="python3"
USER="mld"

echo ""
echo "═══════════════════════════════════════════════"
echo "   Sports Ticker — Pi Setup"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq git python3-pip python3-pil python3-flask fonts-dejavu

# ── 2. Clone or update repo ───────────────────────────────────────────────────
echo "[2/7] Cloning repo..."
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "  Repo already cloned — pulling latest..."
    git -C "$PROJECT_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

# Allow root to run git in this directory (service runs as root)
git config --global --add safe.directory "$PROJECT_DIR"

# ── 3. Python dependencies ───────────────────────────────────────────────────
echo "[3/7] Installing Python requirements (ticker controller)..."
cd "$PROJECT_DIR"
$PYTHON -m pip install -r ticker_controller/requirements.txt --break-system-packages 2>/dev/null \
    || $PYTHON -m pip install -r ticker_controller/requirements.txt

# ── 4. RGB Matrix library ─────────────────────────────────────────────────────
echo "[4/7] Installing rpi-rgb-led-matrix Python bindings..."
if ! $PYTHON -c "from rgbmatrix import RGBMatrix" 2>/dev/null; then
    TMP_DIR=$(mktemp -d)
    git clone https://github.com/hzeller/rpi-rgb-led-matrix "$TMP_DIR/rpi-rgb-led-matrix" --depth=1
    cd "$TMP_DIR/rpi-rgb-led-matrix/bindings/python"
    make build-python PYTHON="$PYTHON"
    make install-python PYTHON="$PYTHON"
    cd "$PROJECT_DIR"
    rm -rf "$TMP_DIR"
    echo "  rgbmatrix installed."
else
    echo "  rgbmatrix already available — skipping."
fi

# ── 5. Sudoers entry so updater can restart services without a password ───────
echo "[5/7] Configuring sudoers for service restart..."
SUDOERS_LINE="$USER ALL=(root) NOPASSWD: /bin/systemctl restart ticker-controller, /bin/systemctl restart ticker, /sbin/reboot"
SUDOERS_FILE="/etc/sudoers.d/ticker"
echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
echo "  Sudoers entry written to $SUDOERS_FILE"

# ── 6. Install & enable systemd service ──────────────────────────────────────
echo "[6/7] Installing systemd service..."
# Patch service file to use the actual home directory
sed -i "s|/home/pi|/home/$USER|g" "$SERVICE_SRC"
cp "$SERVICE_SRC" "$SERVICE_DST"
systemctl daemon-reload
systemctl enable ticker-controller
systemctl restart ticker-controller
echo "  Service enabled and started."

# ── 7. Verify ─────────────────────────────────────────────────────────────────
echo "[7/7] Verifying..."
sleep 2
systemctl status ticker-controller --no-pager || true

echo ""
echo "═══════════════════════════════════════════════"
echo "   Setup complete!"
echo "   Logs:    journalctl -u ticker-controller -f"
echo "   Or:      tail -f /home/$USER/ticker.log"
echo "═══════════════════════════════════════════════"
echo ""

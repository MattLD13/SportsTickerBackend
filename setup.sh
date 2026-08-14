#!/usr/bin/env bash
# Install the Pi controller in immutable Git worktrees.
set -euo pipefail

REPO_URL="https://github.com/MattLD13/SportsTickerBackend.git"
BOARD_USER="mld"
RELEASE_ROOT="/opt/sports-ticker"
SOURCE_DIR="$RELEASE_ROOT/source"
RELEASES_DIR="$RELEASE_ROOT/releases"
CURRENT_LINK="$RELEASE_ROOT/current"
DATA_DIR="/home/$BOARD_USER/ticker"
SERVICE_DST="/etc/systemd/system/ticker-controller.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo."
    exit 1
fi

systemctl disable --now ticker.service 2>/dev/null || true
rm -f /etc/systemd/system/ticker.service
rm -f /etc/systemd/system/multi-user.target.wants/ticker.service

apt-get update -qq
apt-get install -y -qq git python3-pip python3-pil python3-flask fonts-dejavu

install -d -o "$BOARD_USER" -g "$BOARD_USER" "$RELEASE_ROOT" "$RELEASES_DIR" "$DATA_DIR"
if [ ! -d "$SOURCE_DIR/.git" ]; then
    sudo -u "$BOARD_USER" git clone "$REPO_URL" "$SOURCE_DIR"
fi

sudo -u "$BOARD_USER" git -C "$SOURCE_DIR" fetch --quiet origin main
REVISION=$(sudo -u "$BOARD_USER" git -C "$SOURCE_DIR" rev-parse origin/main)
RELEASE_DIR="$RELEASES_DIR/$REVISION"
if [ ! -d "$RELEASE_DIR" ]; then
    sudo -u "$BOARD_USER" git -C "$SOURCE_DIR" worktree add --detach "$RELEASE_DIR" "$REVISION"
fi

NEXT_LINK="$RELEASE_ROOT/.current.next"
ln -sfn "$RELEASE_DIR" "$NEXT_LINK"
mv -Tf "$NEXT_LINK" "$CURRENT_LINK"
chown -h "$BOARD_USER:$BOARD_USER" "$CURRENT_LINK"

python3 -m pip install -r "$CURRENT_LINK/requirements.txt" --break-system-packages 2>/dev/null \
    || python3 -m pip install -r "$CURRENT_LINK/requirements.txt"

if ! python3 -c "from rgbmatrix import RGBMatrix" 2>/dev/null; then
    BUILD_DIR=$(mktemp -d)
    git clone --depth=1 https://github.com/hzeller/rpi-rgb-led-matrix "$BUILD_DIR/rpi-rgb-led-matrix"
    make -C "$BUILD_DIR/rpi-rgb-led-matrix/bindings/python" build-python PYTHON=python3
    make -C "$BUILD_DIR/rpi-rgb-led-matrix/bindings/python" install-python PYTHON=python3
    rm -rf "$BUILD_DIR"
fi

echo 'blacklist snd_bcm2835' > /etc/modprobe.d/blacklist-rgb-matrix.conf
sed -i 's/^dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt 2>/dev/null \
    || sed -i 's/^dtparam=audio=on/dtparam=audio=off/' /boot/config.txt 2>/dev/null \
    || true

cat > /etc/sudoers.d/ticker <<EOF
$BOARD_USER ALL=(root) NOPASSWD: /bin/systemctl restart ticker-controller, /bin/systemctl daemon-reload
EOF
chmod 440 /etc/sudoers.d/ticker

install -m 0644 "$CURRENT_LINK/ticker-controller.service" "$SERVICE_DST"
systemctl daemon-reload
systemctl enable ticker-controller
systemctl restart ticker-controller
systemctl status ticker-controller --no-pager

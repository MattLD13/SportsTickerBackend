#!/usr/bin/env python3
"""
OTA updater for the Sports Ticker.

Called by ticker_controller when the backend signals an update is available.
  1. Shows an update UI on the LED matrix (unless --no-display is passed)
  2. git pull
  3. pip install if requirements.txt changed
  4. Restarts the ticker-controller systemd service (which replaces this process)

Usage:
  python3 updater.py               # standalone with LED display
  python3 updater.py --no-display  # called from within running ticker process
"""

import os
import subprocess
import sys
import threading
import time

# ── Project root (directory this file lives in) ──────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_NAME = "ticker-controller"

# ── Service map: which services to restart for each changed path prefix ──────
# Paths are relative to PROJECT_DIR.  Backend and controller can restart
# independently so a pure backend-only push never interrupts the display.
SERVICE_MAP = [
    ("sports_ticker/",      "ticker"),              # Flask backend
    ("app.py",              "ticker"),
    ("ticker_controller/",  SERVICE_NAME),          # LED controller package
    ("updater.py",          SERVICE_NAME),
]


def _ensure_safe_directory():
    """Allow root to operate on a directory owned by another user."""
    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", PROJECT_DIR],
            capture_output=True, check=False,
        )
    except Exception:
        pass


def _git(*args, check=True, capture=True):
    return subprocess.run(
        ["git", "-C", PROJECT_DIR, *args],
        capture_output=capture,
        text=True,
        check=check,
    )


def changed_files_since_last_pull():
    """Return list of files that differ between the current HEAD and origin/main."""
    try:
        _git("fetch", "--quiet")
        result = _git("diff", "--name-only", "HEAD", "origin/main")
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return lines
    except Exception as e:
        print(f"[updater] git diff failed: {e}")
        return []


def services_to_restart(changed):
    """Given a list of changed file paths, return the set of services to restart."""
    restart = set()
    for path in changed:
        for prefix, svc in SERVICE_MAP:
            if path.startswith(prefix) or path == prefix.rstrip("/"):
                restart.add(svc)
    # Always restart the controller if we have no idea (empty changed list)
    if not changed:
        restart.add(SERVICE_NAME)
    return restart


def pip_install_needed(changed):
    return any(p.startswith("requirements") for p in changed)


def restart_service(name):
    try:
        subprocess.run(["sudo", "systemctl", "restart", name], check=True)
        print(f"[updater] Restarted {name}")
    except Exception as e:
        print(f"[updater] Failed to restart {name}: {e}")


# ── Optional LED matrix display ───────────────────────────────────────────────

def _try_show_update_ui(step_ref):
    """Background thread: drive the LED matrix with the update screen."""
    try:
        import math
        from PIL import Image, ImageDraw, ImageFont

        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
            options = RGBMatrixOptions()
            options.rows = 32
            options.cols = 64
            options.chain_length = 6
            options.parallel = 1
            options.hardware_mapping = "regular"
            options.gpio_slowdown = 2
            options.disable_hardware_pulsing = True
            options.drop_privileges = False
            matrix = RGBMatrix(options=options)
        except Exception:
            return  # Not on hardware — skip silently

        try:
            font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 10)
        except Exception:
            font = ImageFont.load_default()

        W, H = 384, 32
        while not step_ref.get("done"):
            t = time.time()
            img = Image.new("RGB", (W, H), (0, 0, 0))
            d = ImageDraw.Draw(img)

            # Scrolling highlight
            bar_x = int((t * 80) % (W + 60)) - 30
            for bx in range(bar_x, bar_x + 60):
                if 0 <= bx < W:
                    alpha = 1.0 - abs(bx - (bar_x + 30)) / 30.0
                    c = int(alpha * 80)
                    d.point((bx, 0), fill=(0, c, c))

            # Spinning dots
            cx, cy = 10, 16
            for i in range(8):
                angle = i * math.pi / 4 + t * 3
                dx = int(cx + math.cos(angle) * 7)
                dy = int(cy + math.sin(angle) * 7)
                br = int(100 + 155 * ((math.sin(angle - t * 3) + 1) / 2))
                d.point((dx, dy), fill=(0, br, br))
            d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(0, 180, 180))

            # Label
            label = str(step_ref.get("step", "UPDATING...")).upper()
            lw = d.textlength(label, font=font)
            d.text(((W - lw) / 2, 1), label, font=font, fill=(200, 220, 220))

            # Bouncing dots
            for i in range(5):
                phase = t * 4 + i * 0.6
                dot_y = 20 + int(math.sin(phase) * 3)
                bx = W // 2 - 12 + i * 6
                d.ellipse((bx, dot_y, bx + 2, dot_y + 2), fill=(0, 200, 255))

            # Indeterminate progress bar
            pulse_w = 80
            px = int((t * 100) % (W + pulse_w)) - pulse_w
            d.rectangle((0, 31, W - 1, 31), fill=(20, 20, 20))
            for bx in range(px, px + pulse_w):
                if 0 <= bx < W:
                    d.point((bx, 31), fill=(0, 180, 80))

            matrix.SetImage(img)
            time.sleep(0.033)

    except Exception as e:
        print(f"[updater] LED display error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _ensure_safe_directory()
    no_display = "--no-display" in sys.argv

    step_ref = {"step": "Checking...", "done": False}

    if not no_display:
        t = threading.Thread(target=_try_show_update_ui, args=(step_ref,), daemon=True)
        t.start()

    print("[updater] Checking for changes...")
    changed = changed_files_since_last_pull()
    print(f"[updater] Changed files: {changed or '(none detected)'}")

    services = services_to_restart(changed)
    needs_pip = pip_install_needed(changed)

    # ── git pull ──────────────────────────────────────────────────────────────
    step_ref["step"] = "Pulling..."
    print("[updater] Running git pull...")
    try:
        result = _git("pull", "--ff-only", capture=False)
    except subprocess.CalledProcessError as e:
        print(f"[updater] git pull failed: {e}")
        step_ref["done"] = True
        sys.exit(1)

    # ── pip install ───────────────────────────────────────────────────────────
    if needs_pip:
        step_ref["step"] = "Installing..."
        print("[updater] requirements.txt changed — running pip install...")
        req_path = os.path.join(PROJECT_DIR, "requirements.txt")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_path,
                 "--break-system-packages", "--quiet"],
                check=True,
            )
        except subprocess.CalledProcessError:
            # Try without --break-system-packages (older pip)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_path, "--quiet"],
                check=False,
            )

    # ── restart services ──────────────────────────────────────────────────────
    step_ref["step"] = "Restarting..."
    time.sleep(0.5)  # let the LED show "Restarting..." briefly

    step_ref["done"] = True

    for svc in sorted(services):
        restart_service(svc)

    print("[updater] Done.")


if __name__ == "__main__":
    main()

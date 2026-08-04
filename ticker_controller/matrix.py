"""RGB matrix abstraction, device ID persistence, and WiFi captive portal."""

import os
import socket
import subprocess
import threading
import time
import uuid

from PIL import Image, ImageDraw
try:
    # optional for emulator
    from PIL import ImageTk
    import tkinter as tk
except Exception:
    ImageTk = None
    tk = None
from flask import Flask, request, render_template_string

from .config import (
    PANEL_W, PANEL_H,
    SETUP_SSID, SETUP_PASS,
    ID_FILE_PATH, ID_FILE_FALLBACK,
    HTML_TEMPLATE,
)

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    RGBMatrix = RGBMatrixOptions = None


def _sound_module_loaded():
    """True if snd_bcm2835 holds the PWM hardware the matrix library wants.

    This is the same check the library makes, for the same reason — but it
    responds to the conflict by calling ``exit(1)``, which systemd turns into a
    restart loop with a dark panel. Testing it here means a Pi that hasn't had
    the module blacklisted quietly falls back to software pulsing instead.
    """
    try:
        with open('/proc/modules') as f:
            return 'snd_bcm2835' in f.read()
    except OSError:
        return True  # Can't tell — assume the conflict and stay safe.


def build_matrix_options():
    """RGBMatrixOptions for the 6-panel chain on the passive HUB75 adapter.

    The adapter wires OE to GPIO18, so the library can time its pulses with the
    PWM hardware, which is both steadier and brighter than software pulsing on
    a chain this long. That needs ``snd_bcm2835`` blacklisted on the Pi (see
    setup.sh), so it is enabled automatically when the module is absent rather
    than assumed. ``TICKER_HW_PULSE=0``/``1`` forces the choice either way.
    """
    options = RGBMatrixOptions()
    options.rows = PANEL_H
    options.cols = 64
    options.chain_length = PANEL_W // 64
    options.parallel = 1
    options.hardware_mapping = 'regular'
    # Pi 4 generally needs 3-4 here; a Zero 2 W is happy at 1-2. The adapter is
    # passive (no level shifters), so err high rather than low.
    options.gpio_slowdown = int(os.environ.get('TICKER_GPIO_SLOWDOWN') or 2)
    hw_pulse = os.environ.get('TICKER_HW_PULSE', '').strip()
    if hw_pulse:
        options.disable_hardware_pulsing = hw_pulse not in ('1', 'true', 'True')
    else:
        options.disable_hardware_pulsing = _sound_module_loaded()
    options.drop_privileges = False
    # 384 columns of 1:16 scan refresh slowly at the default 11 PWM bits, and a
    # low refresh rate is exactly what the eye reads as flicker. Trading colour
    # depth for refresh rate is the cheapest win available.
    options.pwm_bits = int(os.environ.get('TICKER_PWM_BITS') or 8)
    options.pwm_lsb_nanoseconds = 130
    return options


class NullMatrix:
    """No-op RGB matrix fallback so the app can run off-device (e.g., Windows dev)."""

    def __init__(self, width=PANEL_W, height=PANEL_H):
        self.width = width
        self.height = height
        self.brightness = 100
        self._last_image = None

    def SetImage(self, img):
        self._last_image = img

    def Fill(self, r, g, b):
        self._last_image = Image.new("RGB", (self.width, self.height), (int(r), int(g), int(b)))


class EmulatedMatrix:
    """Simple Tkinter-based emulator for the RGB matrix.

    It opens a small window and updates frames via `SetImage`. Set environment
    variable `TICKER_EMULATOR` to `1` to use this emulator.
    """
    def __init__(self, width=PANEL_W, height=PANEL_H, scale=3):
        self.width = width
        self.height = height
        self.scale = int(scale) if scale and int(scale) > 0 else 3
        self.brightness = 100
        self._last_image = None
        self._photo = None
        self._root = None
        self._canvas = None
        if tk is None or ImageTk is None:
            # fallback to NullMatrix behavior if tkinter not available
            return
        try:
            # run Tk in a separate thread
            import threading
            self._root = tk.Tk()
            self._root.title('Ticker Emulator')
            self._root.protocol('WM_DELETE_WINDOW', lambda: None)
            self._canvas = tk.Canvas(self._root, width=self.width * self.scale, height=self.height * self.scale)
            self._canvas.pack()

            def _tk_loop():
                try:
                    self._root.mainloop()
                except Exception:
                    pass

            t = threading.Thread(target=_tk_loop, daemon=True)
            t.start()
        except Exception:
            self._root = None
            self._canvas = None

    def SetImage(self, img):
        if img is None:
            return
        # store last image
        self._last_image = img
        if self._root is None or self._canvas is None:
            return
        try:
            resized = img.resize((self.width * self.scale, self.height * self.scale), Image.NEAREST).convert('RGB')
            self._photo = ImageTk.PhotoImage(resized)
            # clear and draw
            self._canvas.create_image(0, 0, anchor='nw', image=self._photo)
            # force update of the canvas
            try:
                self._canvas.update_idletasks()
                self._canvas.update()
            except Exception:
                pass
        except Exception:
            pass

    def Fill(self, r, g, b):
        img = Image.new("RGB", (self.width, self.height), (int(r), int(g), int(b)))
        self.SetImage(img)


def get_device_id():
    path_to_use = ID_FILE_PATH
    if not os.path.isfile(ID_FILE_PATH):
        try:
            test_uuid = str(uuid.uuid4())
            with open(ID_FILE_PATH, 'w') as f:
                f.write(test_uuid)
        except Exception:
            path_to_use = ID_FILE_FALLBACK
    if os.path.exists(path_to_use):
        with open(path_to_use, 'r') as f:
            return f.read().strip()
    return str(uuid.uuid4())


class WifiPortal:
    def __init__(self, matrix, font):
        self.matrix = matrix
        self.font = font
        self.app = Flask(__name__)

        @self.app.route('/')
        def home():
            return render_template_string(HTML_TEMPLATE, networks=self.get_available_networks())

        @self.app.route('/connect', methods=['POST'])
        def connect():
            ssid = (
                request.form.get('ssid_manual')
                if request.form.get('ssid_select') == "__manual__"
                else request.form.get('ssid_select')
            )
            threading.Thread(target=self.apply_and_reboot, args=(ssid, request.form['password'])).start()
            return "<html><body><h2>Settings Saved. Rebooting...</h2></body></html>"

    def apply_and_reboot(self, s, p):
        try:
            subprocess.run(['nmcli', 'dev', 'wifi', 'connect', s, 'password', p])
        except Exception:
            pass
        time.sleep(3)
        subprocess.run(['reboot'])

    def get_available_networks(self):
        try:
            r = subprocess.run(
                ['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi', 'list'],
                capture_output=True, text=True,
            )
            return sorted(list(set([n for n in r.stdout.split('\n') if n.strip()])))
        except Exception:
            return []

    def check_internet(self):
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except Exception:
            return False

    def run(self):
        if self.check_internet():
            return True
        img = Image.new("RGB", (PANEL_W, PANEL_H), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((2, 2), "WIFI SETUP MODE", font=self.font, fill=(255, 255, 0))
        d.text((2, 12), f"SSID: {SETUP_SSID}", font=self.font, fill=(255, 255, 255))
        self.matrix.SetImage(img.convert("RGB"))
        subprocess.run([
            'nmcli', 'dev', 'wifi', 'hotspot',
            'ifname', 'wlan0', 'ssid', SETUP_SSID, 'password', SETUP_PASS,
        ])
        try:
            self.app.run(host='0.0.0.0', port=80)
        except Exception:
            pass

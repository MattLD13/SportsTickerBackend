"""Persist verified scrolling-card pixels outside the display loop."""

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from collections import OrderedDict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import sys
from threading import Lock
from uuid import uuid4

import PIL
from PIL import features

from ticker.six.assets import AssetPlanner
from ticker.six.protocol.model import canonical_payload_hash


def asset_signatures(assets, scene: Mapping[str, object]) -> tuple[tuple[str, str | None], ...]:
    """Identify the exact prepared image inputs used by a sports card."""
    values = []
    for request in AssetPlanner().plan((scene,)).requests:
        identity = f"{request.url}\0{request.processor}\0{request.size[0]}x{request.size[1]}".encode()
        image = assets.long_term.prepared.get(request)
        digest = None if image is None else sha256(image.convert("RGBA").tobytes()).hexdigest()
        values.append((sha256(identity).hexdigest(), digest))
    return tuple(values)


def _renderer_fingerprint() -> str:
    """Bind cached pixels to the installed renderer code, fonts, and image library."""
    root = Path(__file__).resolve().parents[1]
    digest = sha256(f"{sys.version_info[:2]}:{PIL.__version__}:{features.version_module('freetype2')}".encode())
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".py", ".ttf", ".otf"})
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PreparedPaneCache:
    """Store a small set of scene- and asset-verified card images asynchronously."""

    def __init__(self, assets, *, capacity: int = 32):
        if capacity <= 0:
            raise ValueError("Pane cache capacity must be positive")
        self._assets = assets
        self._directory = Path(assets.directory) / "rendered-panes"
        self._capacity = capacity
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ticker-pane-cache")
        self._fingerprint = None
        self._lock = Lock()
        self._pending = OrderedDict()
        self._saving = False
        self._closing = False
        self._errors = SimpleQueue()

    def _renderer(self):
        if self._fingerprint is None:
            self._fingerprint = _renderer_fingerprint()
        return self._fingerprint

    def load(self, identifier, scene, mode):
        return self._executor.submit(self._load, identifier, scene, mode)

    def signatures(self, scene):
        return asset_signatures(self._assets, scene)

    def save(self, identifier, scene, mode, width, height, rgba, signatures):
        with self._lock:
            self._pending[identifier] = (identifier, scene, mode, width, height, rgba, signatures)
            self._pending.move_to_end(identifier)
            while len(self._pending) > self._capacity:
                self._pending.popitem(last=False)
            if not self._saving:
                self._saving = True
                self._executor.submit(self._drain_saves)

    def errors(self):
        errors = []
        while True:
            try:
                errors.append(self._errors.get_nowait())
            except Empty:
                return tuple(errors)

    def _drain_saves(self):
        count = 0
        while True:
            with self._lock:
                if not self._pending:
                    self._saving = False
                    return
                if count >= 4 and not self._closing:
                    self._executor.submit(self._drain_saves)
                    return
                _, values = self._pending.popitem(last=False)
            try:
                self._save(*values)
            except Exception as error:
                self._errors.put(error)
            count += 1

    def close(self):
        with self._lock:
            self._closing = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _path(self, identifier):
        return self._directory / f"{sha256(identifier.encode()).hexdigest()}.json"

    def _load(self, identifier, scene, mode):
        try:
            path = self._path(identifier)
            if path.stat().st_size > 4_000_000:
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record["schema"] != 1 or record["renderer"] != self._renderer() or record["mode"] != mode
                    or record["scene"] != canonical_payload_hash(scene)):
                return None
            expected = tuple((key, value) for key, value in record["assets"])
            if expected != asset_signatures(self._assets, scene):
                return None
            width, height = record["width"], record["height"]
            if type(width) is not int or type(height) is not int or not 0 < width <= 4096 or not 0 < height <= 128:
                return None
            rgba = b64decode(record["rgba"], validate=True)
            if len(rgba) != width * height * 4 or sha256(rgba).hexdigest() != record["pixels"]:
                return None
            return width, height, rgba
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, Base64Error):
            return None

    def _save(self, identifier, scene, mode, width, height, rgba, signatures):
        record = {"schema": 1, "renderer": self._renderer(), "mode": mode, "scene": canonical_payload_hash(scene),
                  "assets": signatures, "width": width, "height": height, "pixels": sha256(rgba).hexdigest(),
                  "rgba": b64encode(rgba).decode("ascii")}
        path = self._path(identifier)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, path)
            files = [item for item in self._directory.glob("*.json") if re.fullmatch(r"[0-9a-f]{64}\.json", item.name)]
            for item in sorted(files, key=lambda candidate: candidate.stat().st_mtime_ns)[:-self._capacity]:
                item.unlink(missing_ok=True)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

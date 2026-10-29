"""Turn compositions into device messages: templates once, then only changed values.

Each session remembers what its device holds. A change sends the changed values
of each changed screen, the removed screen IDs, and the order if it changed.
A logo URL becomes an asset ID, so the device fetches images only from the core.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from ticker3.contract.templates import PLACEHOLDER, bundle

from .hub import Composition


class Assets:
    """Map each logo URL that a screen uses to a short asset ID."""

    def __init__(self) -> None:
        self.urls: dict[str, str] = {}

    def identify(self, url: str) -> str:
        identifier = hashlib.sha256(url.encode()).hexdigest()[:16]
        self.urls.setdefault(identifier, url)
        return identifier


class DeviceSession:
    def __init__(self, ticker: str, panel: str, send: Callable[[dict[str, Any]], None], assets: Assets) -> None:
        self.ticker, self.panel, self.send, self.assets = ticker, panel, send, assets
        self.bundle: str | None = None
        self.blocks: dict[str, dict[str, Any]] = {}
        self.screens: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.overlays: set[str] = set()

    def start(self, templates: dict[str, dict[str, Any]], composition: Composition, held_bundle: str | None) -> None:
        """Send the templates if the device bundle differs, then the full screen list."""
        self.bundle, self.blocks = bundle(templates, self.panel)
        if held_bundle != self.bundle:
            self.send({"t": "templates", "bundle": self.bundle, "templates": self.blocks})
        screens = self._screens(composition.screens)
        self.screens = {screen["id"]: screen for screen in screens}
        self.order = [screen["id"] for screen in screens]
        overlays = self._screens(composition.overlays)
        self.overlays = {overlay["id"] for overlay in overlays}
        self.send({"t": "screens", "screens": screens, "overlays": overlays})

    def update(self, templates: dict[str, dict[str, Any]], composition: Composition) -> None:
        """Send what changed since the last message."""
        digest, blocks = bundle(templates, self.panel)
        if digest != self.bundle:
            self.bundle, self.blocks = digest, blocks
            self.send({"t": "templates", "bundle": digest, "templates": blocks})
        screens = self._screens(composition.screens)
        upsert = []
        for screen in screens:
            held = self.screens.get(screen["id"])
            if held is None or held["template"] != screen["template"]:
                upsert.append(screen)
                continue
            changed = {key: value for key, value in screen["values"].items() if held["values"].get(key, _MISSING) != value}
            unset = [key for key in held["values"] if key not in screen["values"]]
            if changed or unset:
                upsert.append({"id": screen["id"], "values": changed, **({"unset": unset} if unset else {})})
        order = [screen["id"] for screen in screens]
        remove = [identifier for identifier in self.order if identifier not in set(order)]
        message: dict[str, Any] = {"t": "delta"}
        if upsert:
            message["upsert"] = upsert
        if remove:
            message["remove"] = remove
        if order != [identifier for identifier in self.order if identifier in set(order)] + [
                identifier for identifier in order if identifier not in self.screens]:
            message["order"] = order
        self.screens = {screen["id"]: screen for screen in screens}
        self.order = order
        if len(message) > 1:
            self.send(message)
        for overlay in self._screens(composition.overlays):
            if overlay["id"] not in self.overlays:
                self.send({"t": "overlay", **overlay})
        self.overlays = {overlay["id"] for overlay in composition.overlays}

    def _screens(self, screens) -> list[dict[str, Any]]:
        """Keep the screens that have a block for this panel, and replace logo URLs with asset IDs."""
        result = []
        for screen in screens:
            block = self.blocks.get(screen["template"])
            if block is None:
                continue
            values = dict(screen["values"])
            for part in block["parts"]:
                if part["part"] == "logo":
                    for key in PLACEHOLDER.findall(part["value"]):
                        url = values.get(key)
                        if isinstance(url, str) and url.startswith(("https://", "http://")):
                            values[key] = self.assets.identify(url)
            result.append({"id": screen["id"], "template": screen["template"], "values": values})
        return result


_MISSING = object()

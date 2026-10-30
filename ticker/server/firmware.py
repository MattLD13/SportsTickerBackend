"""Validate and expose one version two firmware release manifest."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import re
from typing import Any


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_MIN_IMAGE_SIZE = 64 * 1024
_MAX_IMAGE_SIZE = 2 * 1024 * 1024 - 4096


@dataclass(frozen=True, slots=True)
class FirmwareManifest:
    """Describe one immutable firmware image that a device can verify."""

    version: str
    target: str
    hardware: str
    binary_url: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        version = str(self.version).strip()
        target = str(self.target).strip().lower()
        hardware = str(self.hardware).strip().lower()
        binary_url = str(self.binary_url).strip()
        sha256 = str(self.sha256).strip().lower()
        if not version:
            raise ValueError("firmware version must not be empty")
        if not target:
            raise ValueError("firmware target must not be empty")
        if not hardware:
            raise ValueError("firmware hardware must not be empty")
        parsed_url = urlparse(binary_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("firmware binary_url must be an absolute HTTPS URL")
        size = int(self.size)
        if size < _MIN_IMAGE_SIZE or size > _MAX_IMAGE_SIZE:
            raise ValueError("firmware size is outside the supported image bounds")
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("firmware sha256 must contain 64 hexadecimal characters")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "hardware", hardware)
        object.__setattr__(self, "binary_url", binary_url)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "sha256", sha256)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FirmwareManifest":
        """Parse one manifest mapping at the backend contract boundary."""

        if not isinstance(value, Mapping):
            raise ValueError("firmware manifest must be an object")
        required = {"version", "target", "hardware", "binary_url", "size", "sha256"}
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError(f"firmware manifest is missing: {', '.join(missing)}")
        return cls(
            version=value["version"],
            target=value["target"],
            hardware=value["hardware"],
            binary_url=value["binary_url"],
            size=value["size"],
            sha256=value["sha256"],
        )

    @classmethod
    def from_environment(cls) -> "FirmwareManifest | None":
        """Load a release manifest from one JSON file or complete environment declaration."""

        manifest_path = os.environ.get("TICKER_FIRMWARE_MANIFEST_PATH", "").strip()
        if manifest_path:
            try:
                value = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ValueError("TICKER_FIRMWARE_MANIFEST_PATH must contain valid JSON") from error
            return cls.from_mapping(value)

        values = {
            "version": os.environ.get("TICKER_MINI_FIRMWARE_VERSION", "").strip(),
            "target": os.environ.get("TICKER_MINI_FIRMWARE_TARGET", "esp32s3").strip(),
            "hardware": os.environ.get("TICKER_MINI_FIRMWARE_HARDWARE", "esp32-s3").strip(),
            "binary_url": os.environ.get("TICKER_MINI_FIRMWARE_URL", "").strip(),
            "size": os.environ.get("TICKER_MINI_FIRMWARE_SIZE", "").strip(),
            "sha256": os.environ.get("TICKER_MINI_FIRMWARE_SHA256", "").strip(),
        }
        if not any(values[key] for key in ("version", "binary_url", "size", "sha256")):
            return None
        if not all(values[key] for key in ("version", "binary_url", "size", "sha256")):
            raise ValueError("mini firmware environment variables must be complete")
        return cls.from_mapping(values)

    def to_mapping(self) -> dict[str, Any]:
        """Return the stable JSON manifest contract."""

        return {
            "version": self.version,
            "target": self.target,
            "hardware": self.hardware,
            "binary_url": self.binary_url,
            "size": self.size,
            "sha256": self.sha256,
        }


__all__ = ["FirmwareManifest"]

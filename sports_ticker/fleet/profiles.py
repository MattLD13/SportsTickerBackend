"""Typed hardware profiles and display capabilities for fleet devices."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


PROFILE_NORMAL = "normal"
PROFILE_MINI = "mini"
PROFILE_CUSTOM = "custom"
PROFILE_NAMES = frozenset((PROFILE_NORMAL, PROFILE_MINI, PROFILE_CUSTOM))


@dataclass(frozen=True, slots=True)
class DisplayGeometry:
    """Describe the logical display surface reported by one ticker."""

    width: int
    height: int
    panel_count: int
    orientation: str = "landscape"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.panel_count <= 0:
            raise ValueError("display geometry dimensions and panel_count must be positive")
        orientation = str(self.orientation).strip().lower() or "landscape"
        if orientation not in {"landscape", "portrait"}:
            raise ValueError("display orientation must be landscape or portrait")
        object.__setattr__(self, "orientation", orientation)

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-compatible geometry mapping."""

        return {
            "width": self.width,
            "height": self.height,
            "panel_count": self.panel_count,
            "orientation": self.orientation,
        }


@dataclass(frozen=True, slots=True)
class TickerCapabilities:
    """Describe content and runtime capabilities for one hardware profile."""

    modes: tuple[str, ...]
    asset_cache: bool
    ota: bool
    color_depth: int = 24

    def __post_init__(self) -> None:
        modes = tuple(dict.fromkeys(str(mode).strip().lower() for mode in self.modes if str(mode).strip()))
        if not modes:
            raise ValueError("ticker capabilities need at least one mode")
        if self.color_depth <= 0:
            raise ValueError("color_depth must be positive")
        object.__setattr__(self, "modes", modes)
        object.__setattr__(self, "asset_cache", bool(self.asset_cache))
        object.__setattr__(self, "ota", bool(self.ota))

    def to_mapping(self) -> dict[str, Any]:
        """Return one JSON-compatible capability mapping."""

        return {
            "modes": list(self.modes),
            "asset_cache": self.asset_cache,
            "ota": self.ota,
            "color_depth": self.color_depth,
        }


@dataclass(frozen=True, slots=True)
class TickerProfile:
    """Describe one supported ticker product and its display contract."""

    product_family: str
    hardware: str
    firmware: str
    display: DisplayGeometry
    capabilities: TickerCapabilities

    def __post_init__(self) -> None:
        family = str(self.product_family).strip().lower()
        if family not in PROFILE_NAMES:
            raise ValueError(f"unsupported product_family: {family}")
        object.__setattr__(self, "product_family", family)
        object.__setattr__(self, "hardware", str(self.hardware).strip() or "unknown")
        object.__setattr__(self, "firmware", str(self.firmware).strip() or "unknown")

    def to_mapping(self) -> dict[str, Any]:
        """Return the persisted profile representation."""

        return {
            "product_family": self.product_family,
            "hardware": self.hardware,
            "firmware": self.firmware,
            "display": self.display.to_mapping(),
            "capabilities": self.capabilities.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None, *, metadata: Mapping[str, Any] | None = None) -> "TickerProfile":
        """Parse one explicit profile or infer a legacy profile from metadata."""

        source = dict(value or {})
        raw_metadata = metadata or {}
        build = str(source.get("firmware") or raw_metadata.get("build") or "unknown")
        family = str(source.get("product_family") or "").strip().lower()
        if not family:
            capabilities = raw_metadata.get("capabilities")
            family = PROFILE_MINI if "esp32" in build.lower() or isinstance(capabilities, (list, tuple)) and "sports" in capabilities else PROFILE_NORMAL
        if family == PROFILE_NORMAL:
            defaults = {
                "hardware": "pi-zero-2w",
                "display": {"width": 384, "height": 32, "panel_count": 6},
                "capabilities": {"modes": ["sports", "stock", "weather", "music", "flights", "airports", "clock"], "asset_cache": True, "ota": True},
            }
        elif family == PROFILE_MINI:
            defaults = {
                "hardware": "esp32-s3",
                "display": {"width": 64, "height": 32, "panel_count": 1},
                "capabilities": {"modes": ["sports"], "asset_cache": False, "ota": True, "color_depth": 16},
            }
        else:
            defaults = {}
        display = dict(defaults.get("display", {}))
        display.update(source.get("display") if isinstance(source.get("display"), Mapping) else {})
        capabilities = dict(defaults.get("capabilities", {}))
        capabilities.update(source.get("capabilities") if isinstance(source.get("capabilities"), Mapping) else {})
        if family == PROFILE_CUSTOM and ("width" not in display or "height" not in display or "panel_count" not in display):
            raise ValueError("custom profiles need display width, height, and panel_count")
        return cls(
            product_family=family,
            hardware=str(source.get("hardware") or defaults.get("hardware") or "custom"),
            firmware=build,
            display=DisplayGeometry(
                int(display["width"]),
                int(display["height"]),
                int(display["panel_count"]),
                str(display.get("orientation", "landscape")),
            ),
            capabilities=TickerCapabilities(
                tuple(capabilities.get("modes", ())),
                bool(capabilities.get("asset_cache", False)),
                bool(capabilities.get("ota", False)),
                int(capabilities.get("color_depth", 24)),
            ),
        )


def profile_from_metadata(metadata: Mapping[str, Any]) -> TickerProfile:
    """Return one profile from durable device metadata."""

    raw = metadata.get("profile")
    return TickerProfile.from_mapping(raw if isinstance(raw, Mapping) else None, metadata=metadata)

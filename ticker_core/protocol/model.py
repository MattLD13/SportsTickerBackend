"""Validate version two ticker responses at the Pi boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, TypeAlias

from ticker_core._enum import StrEnum


JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]


_CONTENT_FAMILY_ORDER = {
    "sports": 0,
    "golf": 1,
    "racing": 2,
    "weather": 3,
    "music": 4,
    "flights": 5,
    "airports": 6,
    "stock": 7,
    "clock": 8,
    "status": 9,
}


class PayloadValidationError(ValueError):
    """Report an invalid version two backend response."""


class DeviceState(StrEnum):
    """Name the effective display state from the version two settings."""

    ACTIVE = "active"
    PAIRING = "pairing"


def _freeze(value: Any, path: str = "payload") -> FrozenJson:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJson] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise PayloadValidationError(f"{path} has a non-string key")
            frozen[key] = _freeze(child, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child, f"{path}[]") for child in value)
    raise PayloadValidationError(f"{path} has unsupported value type {type(value).__name__}")


def _mapping(value: Any, path: str) -> Mapping[str, FrozenJson]:
    if not isinstance(value, Mapping):
        raise PayloadValidationError(f"{path} must be an object")
    frozen = _freeze(value, path)
    assert isinstance(frozen, Mapping)
    return frozen


def _items(value: Any, path: str) -> tuple[Mapping[str, FrozenJson], ...]:
    if not isinstance(value, (list, tuple)):
        raise PayloadValidationError(f"{path} must be a list")
    return tuple(_mapping(item, f"{path}[{index}]") for index, item in enumerate(value))


def _string(value: Any, path: str, *, default: str | None = None) -> str | None:
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise PayloadValidationError(f"{path} must be a string")
    return value


def _number(value: Any, path: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PayloadValidationError(f"{path} must be a number")
    return float(value)


def _boolean(value: Any, path: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PayloadValidationError(f"{path} must be a boolean")
    return value


def _thaw(value: FrozenJson) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable hash for a JSON-compatible payload."""

    frozen = _mapping(payload, "payload")
    try:
        encoded = json.dumps(
            _thaw(frozen), allow_nan=False, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PayloadValidationError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _display_payload_hash(payload: Mapping[str, Any]) -> str:
    """Hash display data while excluding transport-only snapshot fields."""

    normalized = _thaw(_mapping(payload, "payload"))
    snapshot = normalized.get("snapshot")
    if isinstance(snapshot, dict):
        snapshot.pop("observed_at", None)
        snapshot.pop("revision", None)
    return canonical_payload_hash(normalized)


def _render_data(family: str, kind: str, data: Mapping[str, FrozenJson]) -> Mapping[str, FrozenJson]:
    """Prepare canonical item data for the existing 384x32 renderer catalog."""

    rendered = dict(data)
    canonical = data.get("canonical")
    if isinstance(canonical, Mapping):
        for key, value in canonical.items():
            rendered[key] = value
    rendered["family"] = family
    rendered["kind"] = kind
    rendered["type"] = _renderer_type(family, kind)
    if not str(rendered.get("sport", "")).strip():
        rendered["sport"] = _renderer_sport(family, kind, rendered)
    return _mapping(rendered, "content.data")


def _renderer_type(family: str, kind: str) -> str:
    if family == "stock":
        return "stock_ticker"
    if family == "flights":
        return "flight_visitor"
    if family == "airports":
        return "flight_airport_hud"
    return kind


def _renderer_sport(family: str, kind: str, data: Mapping[str, FrozenJson]) -> str:
    if family == "sports":
        canonical = data.get("canonical")
        if isinstance(canonical, Mapping):
            league = canonical.get("league")
            if isinstance(league, str) and league:
                return league
        league = data.get("league")
        return str(league) if league is not None else "sports"
    if family in {"flights", "airports"}:
        return "flight"
    return family or kind


@dataclass(frozen=True, slots=True)
class ContentItem(Mapping[str, FrozenJson]):
    """Represent one canonical version two content item."""

    id: str
    family: str
    kind: str
    is_shown: bool
    data: Mapping[str, FrozenJson]

    def __getitem__(self, key: str) -> FrozenJson:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def from_payload(cls, payload: Any, path: str) -> "ContentItem":
        envelope = _mapping(payload, path)
        identifier = _string(envelope.get("id"), f"{path}.id")
        family = _string(envelope.get("family"), f"{path}.family")
        kind = _string(envelope.get("kind"), f"{path}.kind")
        if not identifier or not family or not kind:
            raise PayloadValidationError(f"{path} needs non-empty id, family, and kind")
        return cls(
            id=identifier,
            family=family,
            kind=kind,
            is_shown=_boolean(envelope.get("is_shown"), f"{path}.is_shown", True),
            data=_render_data(family, kind, _mapping(envelope.get("data", {}), f"{path}.data")),
        )


@dataclass(frozen=True, slots=True)
class OverlayItem(Mapping[str, FrozenJson]):
    """Represent a version two alert or news overlay for the renderer."""

    id: str
    kind: str
    data: Mapping[str, FrozenJson]

    def __getitem__(self, key: str) -> FrozenJson:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def from_payload(cls, payload: Any, path: str) -> "OverlayItem":
        envelope = _mapping(payload, path)
        identifier = _string(envelope.get("event_id"), f"{path}.event_id")
        kind = _string(envelope.get("kind"), f"{path}.kind")
        if not identifier or not kind:
            raise PayloadValidationError(f"{path} needs non-empty event_id and kind")
        event = dict(_mapping(envelope.get("payload", {}), f"{path}.payload"))
        event.setdefault("id", identifier)
        event.setdefault("event_id", identifier)
        event.setdefault("kind", kind)
        return cls(identifier, kind, _mapping(event, f"{path}.payload"))


Alert = OverlayItem
NewsItem = OverlayItem


@dataclass(frozen=True, slots=True)
class TickerSettings:
    """Expose display settings from the canonical version two response."""

    mode: str
    sports_presentation: str
    pinned_content_id: str
    brightness: float
    scroll_speed: float
    inverted: bool
    data: Mapping[str, FrozenJson]

    @classmethod
    def from_payload(cls, payload: Any) -> "TickerSettings":
        data = _mapping(payload, "settings")
        mode = _string(data.get("mode"), "settings.mode", default="sports")
        presentation = _string(data.get("sports_presentation"), "settings.sports_presentation", default="rotation")
        pinned = _string(data.get("pinned_content_id"), "settings.pinned_content_id", default="")
        assert mode is not None and presentation is not None and pinned is not None
        return cls(
            mode=mode.strip().lower() or "sports",
            sports_presentation=presentation.strip().lower() or "rotation",
            pinned_content_id=pinned.strip(),
            brightness=_number(data.get("brightness"), "settings.brightness", 100.0),
            scroll_speed=_number(data.get("scroll_speed"), "settings.scroll_speed", 0.05),
            inverted=_boolean(data.get("inverted"), "settings.inverted", False),
            data=data,
        )


@dataclass(frozen=True, slots=True)
class TickerResponse:
    """Represent one complete `/api/v2/tickers/<id>/data` response."""

    status: DeviceState
    ticker_id: str
    pairing_code: str | None
    settings: TickerSettings
    content: tuple[ContentItem, ...]
    alerts: tuple[Alert, ...]
    news: tuple[NewsItem, ...]
    update_version: str | None
    reboot_request_id: str | None
    payload_key: str
    data: Mapping[str, FrozenJson]

    @property
    def fingerprint(self) -> str:
        return self.payload_key

    def to_payload(self) -> dict[str, Any]:
        """Return one mutable JSON payload for a process boundary."""

        value = _thaw(self.data)
        assert isinstance(value, dict)
        return value

    def __reduce__(self):
        """Keep process transfers serializable without reparsing twice."""
        settings = self.settings
        serialized = (
            self.status.value,
            self.ticker_id,
            self.pairing_code,
            (
                settings.mode,
                settings.sports_presentation,
                settings.pinned_content_id,
                settings.brightness,
                settings.scroll_speed,
                settings.inverted,
                _thaw(settings.data),
            ),
            tuple((item.id, item.family, item.kind, item.is_shown, _thaw(item.data)) for item in self.content),
            tuple((item.id, item.kind, _thaw(item.data)) for item in self.alerts),
            tuple((item.id, item.kind, _thaw(item.data)) for item in self.news),
            self.update_version,
            self.reboot_request_id,
            self.payload_key,
            _thaw(self.data),
        )
        return _restore_pickled_response, (serialized,)

    @classmethod
    def from_payload(cls, payload: Any) -> "TickerResponse":
        data = _mapping(payload, "response")
        if data.get("api_version") != "v2":
            raise PayloadValidationError("response.api_version must be v2")
        snapshot = _mapping(data.get("snapshot"), "response.snapshot")
        ticker_id = _string(snapshot.get("ticker_id"), "response.snapshot.ticker_id")
        if not ticker_id or not ticker_id.strip():
            raise PayloadValidationError("response.snapshot.ticker_id must be a non-empty string")
        settings = TickerSettings.from_payload(data.get("settings", {}))
        content_root = _mapping(data.get("content", {}), "response.content")
        content: list[ContentItem] = []
        for family in sorted(content_root, key=lambda value: (_CONTENT_FAMILY_ORDER.get(value, 99), value)):
            records = content_root[family]
            if not isinstance(records, tuple):
                raise PayloadValidationError(f"response.content.{family} must be a list")
            for index, item in enumerate(_items(records, f"response.content.{family}")):
                parsed = ContentItem.from_payload(item, f"response.content.{family}[{index}]")
                if parsed.family != family:
                    raise PayloadValidationError(f"response.content.{family}[{index}].family does not match its group")
                content.append(parsed)

        events = _mapping(data.get("events", {}), "response.events")
        alerts = tuple(
            OverlayItem.from_payload(item, f"response.events.alerts[{index}]")
            for index, item in enumerate(_items(events.get("alerts", ()), "response.events.alerts"))
        )
        news = tuple(
            OverlayItem.from_payload(item, f"response.events.news[{index}]")
            for index, item in enumerate(_items(events.get("news", ()), "response.events.news"))
        )
        meta = _mapping(data.get("meta", {}), "response.meta")
        pairing = _mapping(meta.get("pairing", {}), "response.meta.pairing")
        pairing_code = pairing.get("code")
        if pairing_code is not None and not isinstance(pairing_code, str):
            raise PayloadValidationError("response.meta.pairing.code must be a string")
        update = _mapping(meta.get("update", {}), "response.meta.update")
        update_version = update.get("version")
        if update_version is not None and not isinstance(update_version, str):
            raise PayloadValidationError("response.meta.update.version must be a string")
        reboot = _mapping(meta.get("reboot", {}), "response.meta.reboot")
        reboot_request_id = reboot.get("id")
        if reboot_request_id is not None and not isinstance(reboot_request_id, str):
            raise PayloadValidationError("response.meta.reboot.id must be a string")
        return cls(
            status=DeviceState.PAIRING if settings.mode == "pairing" else DeviceState.ACTIVE,
            ticker_id=ticker_id.strip(),
            pairing_code=pairing_code,
            settings=settings,
            content=tuple(content),
            alerts=alerts,
            news=news,
            update_version=update_version.strip() if isinstance(update_version, str) else None,
            reboot_request_id=reboot_request_id.strip() if isinstance(reboot_request_id, str) else None,
            payload_key=_display_payload_hash(data),
            data=data,
        )


DisplayPayload = TickerResponse


def _restore_pickled_response(serialized: tuple[Any, ...]) -> TickerResponse:
    """Restore a validated response without repeating payload validation."""
    (
        status,
        ticker_id,
        pairing_code,
        settings_data,
        content_data,
        alerts_data,
        news_data,
        update_version,
        reboot_request_id,
        payload_key,
        data,
    ) = serialized
    mode, presentation, pinned, brightness, scroll_speed, inverted, raw_settings = settings_data
    settings = TickerSettings(
        mode,
        presentation,
        pinned,
        brightness,
        scroll_speed,
        inverted,
        _frozen_mapping(raw_settings),
    )
    content = tuple(
        ContentItem(identifier, family, kind, is_shown, _frozen_mapping(raw_data))
        for identifier, family, kind, is_shown, raw_data in content_data
    )
    alerts = tuple(OverlayItem(identifier, kind, _frozen_mapping(raw_data)) for identifier, kind, raw_data in alerts_data)
    news = tuple(OverlayItem(identifier, kind, _frozen_mapping(raw_data)) for identifier, kind, raw_data in news_data)
    return TickerResponse(
        DeviceState(status),
        ticker_id,
        pairing_code,
        settings,
        content,
        alerts,
        news,
        update_version,
        reboot_request_id,
        payload_key,
        _frozen_mapping(data),
    )


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, FrozenJson]:
    """Freeze trusted process data without validating it again."""
    frozen = _freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen

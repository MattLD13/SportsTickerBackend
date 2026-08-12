"""Validate and preserve backend display payloads."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, TypeAlias

from ticker_core._enum import StrEnum

from .mode_translation import translate_server_mode


JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]


class PayloadValidationError(ValueError):
    """Report an invalid backend payload."""


class DeviceState(StrEnum):
    """Name the states the backend sends to a ticker."""

    ACTIVE = "ok"
    SLEEP = "sleep"
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
            _thaw(frozen),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PayloadValidationError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class _DataItem(Mapping[str, FrozenJson]):
    """Keep one validated backend object without dropping fields."""

    id: str
    data: Mapping[str, FrozenJson]

    def __getitem__(self, key: str) -> FrozenJson:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def get(self, key: str, default: Any = None) -> FrozenJson | Any:
        return self.data.get(key, default)

    @classmethod
    def from_payload(cls, payload: Any, path: str) -> "_DataItem":
        data = _mapping(payload, path)
        item_id = data.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise PayloadValidationError(f"{path}.id must be a non-empty string")
        return cls(id=item_id, data=data)


@dataclass(frozen=True, slots=True)
class ContentItem(_DataItem):
    """Represent one display content item."""


@dataclass(frozen=True, slots=True)
class Alert(_DataItem):
    """Represent one score alert."""


@dataclass(frozen=True, slots=True)
class NewsItem(_DataItem):
    """Represent one news banner."""


@dataclass(frozen=True, slots=True)
class LocalConfig:
    """Expose display settings and retain all backend settings."""

    mode: str
    brightness: float
    scroll_speed: float
    inverted: bool
    data: Mapping[str, FrozenJson]

    @classmethod
    def from_payload(cls, payload: Any) -> "LocalConfig":
        data = _mapping(payload, "local_config")
        mode = _string(data.get("mode"), "local_config.mode", default="sports")
        assert mode is not None
        return cls(
            mode=translate_server_mode(mode),
            brightness=_number(data.get("brightness"), "local_config.brightness", 100.0),
            scroll_speed=_number(data.get("scroll_speed"), "local_config.scroll_speed", 0.05),
            inverted=_boolean(data.get("inverted"), "local_config.inverted", False),
            data=data,
        )


@dataclass(frozen=True, slots=True)
class GlobalConfig:
    """Expose global device commands and retain all backend settings."""

    update: bool
    update_version: str
    reboot: bool
    data: Mapping[str, FrozenJson]

    @classmethod
    def from_payload(cls, payload: Any) -> "GlobalConfig":
        data = _mapping(payload, "global_config")
        update_version = _string(data.get("update_version"), "global_config.update_version", default="")
        assert update_version is not None
        return cls(
            update=_boolean(data.get("update"), "global_config.update", False),
            update_version=update_version,
            reboot=_boolean(data.get("reboot"), "global_config.reboot", False),
            data=data,
        )


@dataclass(frozen=True, slots=True)
class TickerResponse:
    """Represent one complete `/data` response."""

    status: DeviceState
    pairing_code: str | None
    ticker_id: str | None
    local_config: LocalConfig
    global_config: GlobalConfig
    content: tuple[ContentItem, ...]
    alerts: tuple[Alert, ...]
    news: tuple[NewsItem, ...]
    payload_key: str
    data: Mapping[str, FrozenJson]

    @property
    def fingerprint(self) -> str:
        """Return the canonical response fingerprint."""

        return self.payload_key

    @classmethod
    def from_payload(cls, payload: Any) -> "TickerResponse":
        data = _mapping(payload, "response")
        raw_status = _string(data.get("status"), "response.status", default="ok")
        assert raw_status is not None
        try:
            status = DeviceState(raw_status)
        except ValueError as error:
            raise PayloadValidationError(f"response.status has unsupported value {raw_status!r}") from error

        code = data.get("code")
        if code is not None and not isinstance(code, str):
            raise PayloadValidationError("response.code must be a string")
        ticker_id = data.get("ticker_id")
        if ticker_id is not None and not isinstance(ticker_id, str):
            raise PayloadValidationError("response.ticker_id must be a string")

        content_root = data.get("content", MappingProxyType({}))
        content_data = _mapping(content_root, "response.content")
        sports = content_data.get("sports", ())
        if sports == ():
            content: tuple[ContentItem, ...] = ()
        else:
            content = tuple(
                ContentItem.from_payload(item, f"response.content.sports[{index}]")
                for index, item in enumerate(_items(sports, "response.content.sports"))
            )

        def build_items(name: str, item_type: type[_DataItem]) -> tuple[_DataItem, ...]:
            raw_items = data.get(name, ())
            if raw_items == ():
                return ()
            return tuple(
                item_type.from_payload(item, f"response.{name}[{index}]")
                for index, item in enumerate(_items(raw_items, f"response.{name}"))
            )

        alerts = tuple(build_items("alerts", Alert))
        news = tuple(build_items("news", NewsItem))
        return cls(
            status=status,
            pairing_code=code,
            ticker_id=ticker_id,
            local_config=LocalConfig.from_payload(data.get("local_config", {})),
            global_config=GlobalConfig.from_payload(data.get("global_config", {})),
            content=content,
            alerts=alerts,
            news=news,
            payload_key=canonical_payload_hash(data),
            data=data,
        )


DisplayPayload = TickerResponse

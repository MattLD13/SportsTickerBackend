"""Build the versioned JSON projection for ticker data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
import hashlib
from typing import Any

from ..domain import CONTENT_FAMILIES, ContentItem, DisplaySettings, TickerSnapshot
from ..markets import selected_market_groups
from ..providers.contracts import ProviderHealth
from ..providers.sports_display import matches_followed_team


_SPORTS_FAMILIES = frozenset(("sports", "golf", "racing"))
_MODE_FAMILIES = {
    "sports": _SPORTS_FAMILIES,
}
_FAN_DUEL_JOKE_AD_ID = "sports:fan-dual-joke-ad"
_FAN_DUEL_JOKE_ADS: tuple[dict[str, Any], ...] = (
    {
        "brand": "POLYMARKET",
        "campaign": "Questions Are Everything",
        "style": "market",
        "taglines": (
            "SCROLL ENDS? 2% YES",
            "MARKET: ONE MORE LOOP",
            "SILENCE ODDS: ZERO",
            "{away} MARKET? NO.",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=polymarket.com&sz=64",
        "background": "#080b12",
        "accent": "#2e5cff",
    },
    {
        "brand": "FANDUEL",
        "campaign": "Kick of Destiny 3",
        "style": "kick",
        "taglines": (
            "KICK OF DESTINY? MISS",
            "FANDUEL? FANS TIED.",
            "LIVE ODDS: NEXT TYPO",
            "{away}/{home}: WIDE LEFT",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=fanduel.com&sz=64",
        "background": "#071b2e",
        "accent": "#1696ff",
    },
    {
        "brand": "DRAFTKINGS",
        "campaign": "Take Your Game Anywhere",
        "style": "psa",
        "taglines": (
            "THE CROWN IS BUFFERING",
            "TAKE TICKER ANYWHERE",
            "ROYAL ODDS. BAD WIFI.",
            "{away} TO {home}: KING?",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=draftkings.com&sz=64",
        "background": "#071c12",
        "accent": "#00a94f",
    },
    {
        "brand": "BETMGM",
        "campaign": "Make It Legendary",
        "style": "legendary",
        "taglines": (
            "MAKE IT LEGENDARY-ISH",
            "LEGENDS LOUNGE: FULL",
            "GOLD TEXT. BAD PICKS.",
            "{away_score}-{home_score}: LEGEND",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=betmgm.com&sz=64",
        "background": "#11100d",
        "accent": "#d4af37",
    },
    {
        "brand": "PRIZEPICKS",
        "campaign": "Run Your Game",
        "style": "neon",
        "taglines": (
            "RUN GAME. WALK DOG.",
            "MORE? LESS? ASK TICK.",
            "GROUP CHAT PICKED IT",
            "{away}/{home}: PICK?",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=prizepicks.com&sz=64",
        "background": "#101c14",
        "accent": "#a7ff00",
    },
    {
        "brand": "UNDERDOG",
        "campaign": "Unleash Your Dog",
        "style": "dog",
        "taglines": (
            "UNLEASH DOG. FETCH.",
            "HIGHER? LOWER? BARK.",
            "DOG ATE OUR PARLAY.",
            "FETCH {away}. BARK.",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=underdogfantasy.com&sz=64",
        "background": "#1e130c",
        "accent": "#f47b20",
    },
    {
        "brand": "CAESARS SPORTSBOOK",
        "campaign": "Caesar & Cleo",
        "style": "roman",
        "taglines": (
            "BET LIKE CAESAR. NAP.",
            "EMPEROR HAS NO LOCKS.",
            "HAIL THE BONUS TYPO.",
            "{home}: DECREE?",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=caesars.com&sz=64",
        "background": "#1d0b0b",
        "accent": "#e0bd66",
    },
    {
        "brand": "BET365",
        "campaign": "Never Ordinary Moments",
        "style": "365",
        "taglines": (
            "NEVER ORDINARY. OFF.",
            "NO ORDINARY TYPOS.",
            "365 DAYS. BAD PICKS.",
            "{away}: NO ORDINARY",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=bet365.com&sz=64",
        "background": "#06220f",
        "accent": "#0acb58",
    },
    {
        "brand": "FANATICS SPORTSBOOK",
        "campaign": "Bet on Kendall",
        "style": "fanatics",
        "taglines": (
            "KURSE PICKED OUR FONT",
            "JERSEY DROP: MISSED",
            "FANCASH? TAKES COINS.",
            "{away}: FAN MODE",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=fanatics.com&sz=64",
        "background": "#17100a",
        "accent": "#ff5b1f",
    },
    {
        "brand": "HARD ROCK BET",
        "campaign": "Roll With Us",
        "style": "rock",
        "taglines": (
            "ROLL WITH US. SCROLL.",
            "NOT THE HOUSE. LEDS.",
            "BET PARTY: NO INVITE.",
            "{home} ROCKS? MAYBE.",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=hardrock.bet&sz=64",
        "background": "#17120b",
        "accent": "#f4c542",
    },
    {
        "brand": "KALSHI",
        "campaign": "Trade on Anything",
        "style": "exchange",
        "taglines": (
            "TRADE ANYTHING. THIS.",
            "KALSHI! TOO LOUD.",
            "MORE FORECASTS.",
            "{away}/{home}: TRADE?",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=kalshi.com&sz=64",
        "background": "#0b1020",
        "accent": "#6da0ff",
    },
    {
        "brand": "BALLY BET",
        "campaign": "More Than a Name",
        "style": "bally",
        "taglines": (
            "MORE NAME. LESS PX.",
            "BALLY BET: MORE BALLY.",
            "NO-STRESS. BAD FONT.",
            "{home} SAYS MAYBE",
        ),
        "logo": "https://www.google.com/s2/favicons?domain=ballybet.com&sz=64",
        "background": "#180a0c",
        "accent": "#f14343",
    },
)


def project_data_v2(
    snapshot: TickerSnapshot,
    health: ProviderHealth | Mapping[str, Any],
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a new JSON-ready version two data projection."""

    if not isinstance(snapshot, TickerSnapshot):
        raise TypeError("snapshot must be a TickerSnapshot")
    if not isinstance(meta, Mapping):
        raise TypeError("meta must be a mapping")

    copied_meta = _json_value(meta)
    if not isinstance(copied_meta, dict):
        raise TypeError("meta must produce a mapping")

    content: dict[str, list[dict[str, Any]]] = {
        family: [] for family in CONTENT_FAMILIES
    }
    for item in snapshot.content:
        family = item.family if item.family in content else item.family
        content.setdefault(family, []).append(_content_item(item))

    return {
        "api_version": "v2",
        "snapshot": {
            "ticker_id": str(snapshot.ticker_id),
            "revision": snapshot.revision,
            "observed_at": _json_value(snapshot.observed_at),
            "stale": _stale_value(meta),
        },
        "settings": _settings_value(snapshot.effective_settings),
        "content": content,
        "events": {
            "alerts": _overlay_items(snapshot.alerts, "score_alert"),
            "news": _overlay_items(snapshot.news, "news"),
        },
        "health": _health_value(health),
        "meta": copied_meta,
    }


def _settings_value(settings: DisplaySettings) -> dict[str, Any]:
    """Copy canonical display settings into a JSON-ready mapping."""

    if not isinstance(settings, DisplaySettings):
        raise TypeError("snapshot settings must be DisplaySettings")
    return {
        "active_sports": _json_value(settings.active_sports),
        "active_conferences": _json_value(settings.active_conferences),
        "my_teams": list(settings.my_teams),
        "mode": settings.mode,
        "sports_filter": settings.sports_filter,
        "sports_presentation": settings.sports_presentation,
        "pinned_content_id": settings.pinned_content_id,
        "fan_duel_joke_ad": settings.fan_duel_joke_ad,
        "brightness": settings.brightness,
        "inverted": settings.inverted,
        "timezone": settings.timezone,
        "weather_city": settings.weather_city,
        "weather_lat": settings.weather_lat,
        "weather_lon": settings.weather_lon,
        "airport_code_iata": settings.airport_code_iata,
        "airport_code_icao": settings.airport_code_icao,
        "airport_name": settings.airport_name,
        "track_flight_id": settings.track_flight_id,
        "track_guest_name": settings.track_guest_name,
        "live_delay_mode": settings.live_delay_mode,
        "live_delay_seconds": settings.live_delay_seconds,
        "scroll_seamless": settings.scroll_seamless,
        "scroll_speed": settings.scroll_speed,
        "score_alerts": settings.score_alerts,
    }


def select_display_content(
    content: Mapping[str, list[dict[str, Any]]],
    settings: Mapping[str, Any],
    allowed_modes: Iterable[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return capability-compatible mode content and mark eligible records."""

    mode = str(settings.get("mode") or "sports").strip().lower()
    supported = tuple(dict.fromkeys(str(item).strip().lower() for item in (allowed_modes or ()) if str(item).strip()))
    if mode != "pairing" and supported and mode not in supported:
        mode = supported[0]
        if isinstance(settings, dict):
            settings["mode"] = mode
    if mode == "pairing":
        return {}
    families = _MODE_FAMILIES.get(mode, frozenset((mode,)))
    selected = {
        family: list(items)
        for family, items in content.items()
        if family in families and items
    }
    if mode == "sports":
        selected = {
            family: [_sports_item(item, settings) for item in items]
            for family, items in selected.items()
        }
        if _fan_duel_joke_ads_enabled(settings) and selected.get("sports") and not settings.get("pinned_content_id"):
            selected["sports"] = _insert_fan_duel_joke_ads(selected["sports"])
    elif mode == "stock":
        selected["stock"] = _market_items(selected.get("stock", ()), settings)
    return selected


def _sports_item(item: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, Any]:
    """Mark one sports item for rotation, a sports filter, or pinning."""

    projected = dict(item)
    visible = bool(projected.get("is_shown", True))
    pinned = str(settings.get("pinned_content_id") or "").strip()
    if pinned:
        projected["is_shown"] = visible and str(projected.get("id") or "") == pinned
        return projected
    sports_filter = str(settings.get("sports_filter") or "all").strip().lower()
    if sports_filter == "live":
        state = str(_item_data(projected).get("state") or "").strip().lower()
        visible = visible and state in {"in", "half", "crit"}
    elif sports_filter == "my_teams":
        visible = visible and _is_my_team_game(projected, settings)
    projected["is_shown"] = visible
    return projected


def _insert_fan_duel_joke_ads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert one rotating parody card after each six visible sports cards."""

    result: list[dict[str, Any]] = []
    visible_count = 0
    ad_index = 0
    seed = _fan_duel_joke_seed(items)
    brand_order = sorted(
        range(len(_FAN_DUEL_JOKE_ADS)),
        key=lambda index: _stable_ad_number(seed, f"brand:{index}"),
    )
    used_taglines: set[str] = set()
    for item in items:
        result.append(item)
        if not bool(item.get("is_shown", True)):
            continue
        visible_count += 1
        if visible_count % 6 == 0:
            result.append(
                _fan_duel_joke_ad(
                    ad_index,
                    item,
                    seed,
                    brand_order,
                    used_taglines,
                )
            )
            ad_index += 1
    return result


def _fan_duel_joke_seed(items: Iterable[Mapping[str, Any]]) -> str:
    """Return a stable seed for one visible sports collection."""

    visible_ids = sorted(
        str(item.get("id") or "").strip()
        for item in items
        if bool(item.get("is_shown", True)) and str(item.get("id") or "").strip()
    )
    return "|".join(visible_ids) or "sports"


def _stable_ad_number(seed: str, label: str) -> int:
    """Return a repeatable number for pseudo-random ad ordering."""

    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _ad_team_label(value: Any, fallback: str) -> str:
    """Return a short ticker-safe team label."""

    label = str(value or fallback).strip().upper()
    return label[:6] or fallback


def _ad_game_values(item: Mapping[str, Any]) -> dict[str, str]:
    """Return game values that parody taglines can safely reference."""

    data = _item_data(item)
    return {
        "away": _ad_team_label(data.get("away_abbr") or data.get("away_team"), "AWAY"),
        "home": _ad_team_label(data.get("home_abbr") or data.get("home_team"), "HOME"),
        "away_score": str(data.get("away_score", data.get("as", 0))).strip(),
        "home_score": str(data.get("home_score", data.get("hs", 0))).strip(),
    }


def _resolve_ad_tagline(template: Any, item: Mapping[str, Any]) -> str:
    """Resolve a catalog tagline against one scoreboard item."""

    text = str(template)
    for key, value in _ad_game_values(item).items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _fan_duel_joke_ads_enabled(settings: Mapping[str, Any]) -> bool:
    """Return if server-side joke cards have the required live delay."""

    if not bool(settings.get("live_delay_mode")):
        return False
    try:
        return abs(float(settings.get("live_delay_seconds", 0)) - 45.0) < 0.001
    except (TypeError, ValueError):
        return False


def _fan_duel_joke_ad(
    index: int,
    anchor_item: Mapping[str, Any],
    seed: str,
    brand_order: Sequence[int],
    used_taglines: set[str],
) -> dict[str, Any]:
    """Return one stable pseudo-random parody card for the sports rotation."""

    brand_index = brand_order[index % len(brand_order)]
    ad = _FAN_DUEL_JOKE_ADS[brand_index]
    tagline_order = sorted(
        range(len(ad["taglines"])),
        key=lambda tagline_index: _stable_ad_number(
            seed,
            f"tagline:{index}:{tagline_index}",
        ),
    )
    chosen_tagline = next(
        (
            _resolve_ad_tagline(ad["taglines"][tagline_index], anchor_item)
            for tagline_index in tagline_order
            if _resolve_ad_tagline(ad["taglines"][tagline_index], anchor_item)
            not in used_taglines
        ),
        _resolve_ad_tagline(ad["taglines"][tagline_order[0]], anchor_item),
    )
    used_taglines.add(chosen_tagline)
    return {
        "id": f"{_FAN_DUEL_JOKE_AD_ID}-{index + 1}",
        "family": "sports",
        "kind": "fan_duel_joke_ad",
        "is_shown": True,
        "data": {
            "sport": "sports",
            "state": "pre",
            "status": "JOKE AD",
            "headline": ad["brand"],
            "campaign": ad["campaign"],
            "style": ad["style"],
            "tagline": chosen_tagline,
            "detail": "PARODY / NO BETS",
            "logo": ad["logo"],
            "background": ad["background"],
            "accent": ad["accent"],
        },
    }


def _market_items(
    items: list[dict[str, Any]], settings: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return only the enabled market groups from the shared quote snapshot."""

    active = settings.get("active_sports")
    active_mapping = active if isinstance(active, Mapping) else {}
    enabled = {group.id for group in selected_market_groups(active_mapping)}
    return [
        item
        for item in items
        if str(_item_data(item).get("market_group") or "").strip().lower() in enabled
    ]


def _is_my_team_game(item: Mapping[str, Any], settings: Mapping[str, Any]) -> bool:
    """Return if either game team belongs to the selected team list."""

    raw_teams = settings.get("my_teams", ())
    if not raw_teams:
        return False
    data = _item_data(item)
    sport = str(data.get("sport") or "").strip().lower()
    if not sport:
        return False
    for side in ("home_abbr", "away_abbr"):
        team_abbr = str(data.get(side) or "").strip()
        if team_abbr and matches_followed_team(sport, team_abbr, raw_teams):
            return True
    return False


def _item_data(item: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an item data mapping without accepting an invalid payload."""

    data = item.get("data")
    return data if isinstance(data, Mapping) else {}


def _content_item(item: ContentItem) -> dict[str, Any]:
    if not isinstance(item, ContentItem):
        raise TypeError("snapshot content must contain ContentItem values")
    return {
        "id": item.id,
        "family": item.family,
        "kind": item.kind,
        "is_shown": item.is_shown,
        "data": _json_value(item.data),
    }


def _overlay_items(items: tuple[object, ...], default_kind: str) -> list[dict[str, Any]]:
    """Project provider overlays with the event envelope required by every V2 client."""

    projected: list[dict[str, Any]] = []
    for item in items:
        value = _json_value(item)
        if not isinstance(value, Mapping):
            raise TypeError("snapshot overlays must contain mappings")
        record = dict(value)
        event_id = str(record.get("id") or "").strip()
        if not event_id:
            raise ValueError("snapshot overlays must contain an id")
        kind = str(record.get("kind") or default_kind).strip().lower() or default_kind
        projected.append({
            "event_id": event_id,
            "kind": kind,
            "payload": record,
        })
    return projected


def _health_value(health: ProviderHealth | Mapping[str, Any]) -> dict[str, Any]:
    """Copy provider health while keeping it separate from snapshot staleness."""

    if isinstance(health, ProviderHealth):
        return {
            "provider": health.provider,
            "healthy": health.healthy,
            "error": health.error,
        }
    if not isinstance(health, Mapping):
        raise TypeError("health must be ProviderHealth or a mapping")
    return {
        "provider": str(health.get("provider", "provider")),
        "healthy": bool(health.get("healthy", health.get("ok", False))),
        "error": _json_value(health.get("error")),
    }


def _stale_value(meta: Mapping[str, Any]) -> Any:
    """Copy the displayed stale state from explicit metadata."""

    return _json_value(meta.get("stale", False))


def _json_value(value: Any) -> Any:
    """Copy supported immutable values into JSON-compatible containers."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(child) for child in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


__all__ = ["project_data_v2", "select_display_content"]

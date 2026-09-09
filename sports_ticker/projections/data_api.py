"""Build the versioned JSON projection for ticker data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
import random
from typing import Any

from ..domain import CONTENT_FAMILIES, ContentItem, DisplaySettings, TickerSnapshot
from ..markets import selected_market_groups
from ..providers.contracts import ProviderHealth
from ..providers.sports_display import matches_followed_team


_SPORTS_FAMILIES = frozenset(("sports", "golf", "racing"))
_MODE_FAMILIES = {
    "sports": _SPORTS_FAMILIES,
}
_SPORTS_AD_ID = "sports:real-campaign-ad"
_SPORTS_AD_INTERVAL = 3
_SPORTS_AD_REPEAT_WINDOW = 3
_SPORTS_ADS: tuple[dict[str, Any], ...] = (
    {
        "brand": "POLYMARKET",
        "style": "market",
        "spots": (
            {
                "campaign": "Questions Are Everything",
                "copy": "QUESTIONS ARE EVERYTHING",
                "source_url": "https://www.ispot.tv/ad/gcmj/polymarket-predictions-questions-are-everything",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "ASK THE LED AGAIN",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=polymarket.com&sz=64",
        "background": "#080b12",
        "accent": "#2e5cff",
    },
    {
        "brand": "FANDUEL",
        "style": "kick",
        "spots": (
            {
                "campaign": "Kick of Destiny 3",
                "copy": "MAY THE BEST MANNING WIN",
                "source_url": "https://www.ispot.tv/ad/TInL/fanduel-elis-destiny-bet-5-get-200-featuring-peyton-manning-eli-manning",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Kick of Destiny 3: Best Sunday",
                "copy": "AMERICA'S #1 SPORTSBOOK",
                "source_url": "https://www.ispot.tv/ad/TZjJ/fanduel-super-bowl-2025-kick-of-destiny-3-best-sunday-ft-peyton-manning-eli-manning",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Make Every Moment More",
                "copy": "MAKE EVERY MOMENT MORE",
                "source_url": "https://www.ispot.tv/ad/qVkE/fanduel-make-every-moment-mean-more",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Last Call for Football",
                "copy": "PLAY YOUR AD BREAK.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Hunches",
                "copy": "HUNCHES",
                "source_url": "https://www.fanduel.com/about/news/fanduel-upgrades-betting-experience-for-nfl-kickoff-and-offers-fans-best-place-to-bet-on-hunches",
                "source_type": "official",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "ODDS? JUST VIBES.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=fanduel.com&sz=64",
        "background": "#071b2e",
        "accent": "#1696ff",
    },
    {
        "brand": "DRAFTKINGS",
        "style": "psa",
        "spots": (
            {
                "campaign": "All the Sports You Love",
                "copy": "ALL THE ADS YOU LOVE.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Football Gods",
                "copy": "THE CROWN IS YOURS",
                "source_url": "https://www.ispot.tv/ad/fl5v/draftkings-sportsbook-football-gods",
                "source_type": "ad_archive",
            },
            {
                "campaign": "All About Sweat",
                "copy": "NO SWEAT. SAME REGRET.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "THE CROWN IS BUFFERING",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=draftkings.com&sz=64",
        "background": "#071c12",
        "accent": "#00a94f",
    },
    {
        "brand": "BETMGM",
        "style": "legendary",
        "spots": (
            {
                "campaign": "Make It Legendary",
                "copy": "MAKE IT LEGENDARY",
                "source_url": "https://casino.betmgm.com/en/blog/press/betmgm-unveils-first-major-corporate-brand-repositioning-with-make-it-legendary-campaign/",
                "source_type": "official",
            },
            {
                "campaign": "IT'S ON",
                "copy": "IT'S ON. AGAIN.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "The King of Sportsbooks",
                "copy": "THE KING OF SPORTSBOOKS",
                "source_url": "https://www.ispot.tv/ad/bkia/betmgm-nothing-is-better-than-a-win-1000-risk-free-first-bet-ft-jamie-foxx",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Every Snap Is Showtime",
                "copy": "EVERY SNAP IS SHOWTIME",
                "source_url": "https://www.ispot.tv/product/6kT",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "GOLD TEXT. BAD PICKS.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=betmgm.com&sz=64",
        "background": "#11100d",
        "accent": "#d4af37",
    },
    {
        "brand": "PRIZEPICKS",
        "style": "neon",
        "spots": (
            {
                "campaign": "Run Your Game",
                "copy": "RUN YOUR AD BREAK.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "You Already Know",
                "copy": "YOU ALREADY KNOW",
                "source_url": "https://www.ispot.tv/ad/fOCf/prizepicks-sportsbook-you-already-know-bet-5-get-50",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Lock In",
                "copy": "LOCK IN",
                "source_url": "https://www.ispot.tv/brands/6kX/prizepicks",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "GROUP CHAT PICKED IT",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=prizepicks.com&sz=64",
        "background": "#101c14",
        "accent": "#a7ff00",
    },
    {
        "brand": "UNDERDOG",
        "style": "dog",
        "spots": (
            {
                "campaign": "Unleash Your Dog",
                "copy": "UNLEASH YOUR DOG",
                "source_url": "https://www.underdogsports.com/news/underdog-unleashes-paul-walter-hauser-as-the-dog-in-new-national-campaign-and-brand-platform",
                "source_type": "official",
            },
            {
                "campaign": "Turn Your Takes Into Cash",
                "copy": "TURN YOUR TAKES INTO CASH",
                "source_url": "https://www.ispot.tv/brands/5Ud/underdog",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Playoff Picks",
                "copy": "PLAYOFF PICKS. SURE.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Make Picks Right Now",
                "copy": "MAKE PICKS RIGHT NOW",
                "source_url": "https://www.ispot.tv/brands/5Ud/underdog",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "DOG ATE OUR PARLAY.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=underdogfantasy.com&sz=64",
        "logo_plate": "#ffffff",
        "background": "#1e130c",
        "accent": "#f47b20",
    },
    {
        "brand": "CAESARS SPORTSBOOK",
        "style": "roman",
        "spots": (
            {
                "campaign": "We Are All Caesars",
                "copy": "WE ARE ALL CAESARS",
                "source_url": "https://www.ispot.tv/ad/OQ77/caesars-sportsbook-we-are-all-caesars-featuring-jb-smoove",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Rule the World",
                "copy": "RULE THE WORLD",
                "source_url": "https://www.ispot.tv/ad/OUEt/caesars-sportsbook-rule-the-world-featuring-jb-smoove",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "HAIL THE BONUS DRAMA.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=caesars.com&sz=64",
        "background": "#1d0b0b",
        "accent": "#e0bd66",
    },
    {
        "brand": "BET365",
        "style": "365",
        "spots": (
            {
                "campaign": "Winning Is Everything",
                "copy": "WINNING IS EVERYTHING",
                "source_url": "https://news.bet365.com/en-us/article/bet365-launches-winning-is-everything-brand-campaign-across-the-us-and-canada/2026031316172972579",
                "source_type": "official",
            },
            {
                "campaign": "Never Ordinary Moments",
                "copy": "NEVER ORDINARY MOMENTS",
                "source_url": "https://news.bet365.com/en-us/video/never-ordinary-moments-with-commanders-lb-khaleke-hudson/2024011119461981195",
                "source_type": "official",
            },
            {
                "campaign": "In-Play Betting",
                "copy": "IN-PLAY. STILL LOSING.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "365 DAYS. BAD PICKS.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=bet365.com&sz=64",
        "background": "#06220f",
        "accent": "#0acb58",
    },
    {
        "brand": "FANATICS SPORTSBOOK",
        "style": "fanatics",
        "spots": (
            {
                "campaign": "Bet on Kendall",
                "copy": "BET ON KENDALL",
                "source_url": "https://investor.fanatics.com/news/news-details/2026/Kendall-Jenner-Puts-the-Internets-Favorite-Kurse-to-the-Test-in-Fanatics-Sportsbooks--Fanatics-Studios-First-Big-Game-Ad-2026-BRx2zMg4eA/default.aspx",
                "source_type": "official",
            },
            {
                "campaign": "Bet on Kendall",
                "copy": "KURSED?",
                "source_url": "https://investor.fanatics.com/news/news-details/2026/Kendall-Jenner-Puts-the-Internets-Favorite-Kurse-to-the-Test-in-Fanatics-Sportsbooks--Fanatics-Studios-First-Big-Game-Ad-2026-BRx2zMg4eA/default.aspx",
                "source_type": "official",
            },
            {
                "campaign": "Town Hall: FanCash",
                "copy": "TOWN HALL: FANCASH",
                "source_url": "https://www.ispot.tv/ad/SYmR/fanatics-sportsbook-town-hall-fancash-featuring-luke-wilson",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "FANCASH? CASH-ISH.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=fanatics.com&sz=64",
        "logo_plate": "#ffffff",
        "background": "#17100a",
        "accent": "#ff5b1f",
    },
    {
        "brand": "HARD ROCK BET",
        "style": "rock",
        "spots": (
            {
                "campaign": "Roll With Us",
                "copy": "ROLL WITH US",
                "source_url": "https://www.hardrock.bet/about-us/",
                "source_type": "official",
            },
            {
                "campaign": "The Hard Rock Bet Party",
                "copy": "THE HARD ROCK BET PARTY",
                "source_url": "https://www.hardrock.bet/news/hard-rock-bet-invites-fans-to-the-hard-rock-bet-party/",
                "source_type": "official",
            },
            {
                "campaign": "You Did It, Florida",
                "copy": "YOU DID IT. WE MADE ADS.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "ROLL WITH US. SCROLL.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=hardrock.bet&sz=64",
        "background": "#17120b",
        "accent": "#f4c542",
    },
    {
        "brand": "KALSHI",
        "style": "exchange",
        "spots": (
            {
                "campaign": "Servicio a la Habitación",
                "copy": "SERVICIO A LA HABITACION",
                "source_url": "https://news.kalshi.com/p/kalshi-j-balvin-advertising-campaign",
                "source_type": "official",
            },
            {
                "campaign": "Your Opinion: Basketball",
                "copy": "YOUR OPINION: BASKETBALL",
                "source_url": "https://www.ispot.tv/ad/gD8I/kalshi-predictions-your-opinion-basketball",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Giant Wide Receiver Hands",
                "copy": "GIANT RECEIVER HANDS",
                "source_url": "https://www.ispot.tv/ad/g5a2/kalshi-giant-wide-receiver-hands",
                "source_type": "ad_archive",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "FORECAST: MORE ADS.",
                "source_url": None,
                "source_type": "parody",
            },
        ),
        "logo": "https://www.google.com/s2/favicons?domain=kalshi.com&sz=64",
        "background": "#0b1020",
        "accent": "#6da0ff",
    },
    {
        "brand": "BALLY BET",
        "style": "bally",
        "spots": (
            {
                "campaign": "More Than a Name",
                "copy": "MORE THAN A NAME. AN AD.",
                "source_url": None,
                "source_type": "parody",
            },
            {
                "campaign": "Ticker Intermission",
                "copy": "NO STRESS. JUST BAD BEATS.",
                "source_url": None,
                "source_type": "parody",
            },
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
        if _sports_ads_enabled(settings) and selected.get("sports") and not settings.get("pinned_content_id"):
            selected["sports"] = _insert_sports_ads(selected["sports"])
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


def _insert_sports_ads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert one fresh random campaign card after each three visible sports cards."""

    result: list[dict[str, Any]] = []
    visible_count = 0
    ad_index = 0
    rng = _sports_ad_rng()
    brand_pool: list[int] = []
    recent_brands: list[int] = []
    used_copies: set[str] = set()
    for item in items:
        result.append(item)
        if not bool(item.get("is_shown", True)):
            continue
        visible_count += 1
        if visible_count % _SPORTS_AD_INTERVAL == 0:
            if not brand_pool:
                brand_pool = _random_brand_order(rng)
            eligible_brands = [
                brand_index
                for brand_index in brand_pool
                if brand_index not in recent_brands
            ] or brand_pool
            brand_index = rng.choice(eligible_brands)
            brand_pool.remove(brand_index)
            result.append(
                _sports_ad(
                    ad_index,
                    rng,
                    brand_index,
                    used_copies,
                )
            )
            recent_brands = [*recent_brands, brand_index][-_SPORTS_AD_REPEAT_WINDOW:]
            ad_index += 1
    return result


def _sports_ad_rng() -> random.Random:
    """Return a fresh random source for one server projection."""

    return random.SystemRandom()


def _random_brand_order(rng: random.Random) -> list[int]:
    """Return a shuffled brand pool for the next ad cycle."""

    order = list(range(len(_SPORTS_ADS)))
    rng.shuffle(order)
    return order


def _sports_ads_enabled(settings: Mapping[str, Any]) -> bool:
    """Return if server-side campaign cards have the required live delay."""

    if not bool(settings.get("live_delay_mode")):
        return False
    try:
        return abs(float(settings.get("live_delay_seconds", 0)) - 45.0) < 0.001
    except (TypeError, ValueError):
        return False


def _sports_ad(
    index: int,
    rng: random.Random,
    brand_index: int,
    used_copies: set[str],
) -> dict[str, Any]:
    """Return one randomly selected sourced or filler card for the sports rotation."""

    ad = _SPORTS_ADS[brand_index]
    available_spots = tuple(
        spot
        for spot in ad["spots"]
        if str(spot["copy"]) not in used_copies
    )
    chosen_spot = rng.choice(available_spots or ad["spots"])
    used_copies.add(str(chosen_spot["copy"]))
    return {
        "id": f"{_SPORTS_AD_ID}-{index + 1}",
        "family": "sports",
        "kind": "fan_duel_joke_ad",
        "is_shown": True,
        "data": {
            "sport": "sports",
            "state": "pre",
            "status": "SPORTS AD",
            "headline": ad["brand"],
            "campaign": chosen_spot["campaign"],
            "style": ad["style"],
            "tagline": chosen_spot["copy"],
            "detail": "PARODY",
            "source_url": chosen_spot.get("source_url"),
            "source_type": chosen_spot["source_type"],
            "logo": ad["logo"],
            "logo_plate": ad.get("logo_plate"),
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

"""Compose hardware-only April Fools sports campaign cards."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import random
from typing import Any

from ticker_core.runtime.model import Content, frozen_mapping


APRIL_FOOLS_MONTH = 4
APRIL_FOOLS_DAY = 1
AD_INTERVAL = 3
AD_REPEAT_WINDOW = 3
AD_ID = "sports:april-fools-ad"


SPORTS_ADS: tuple[dict[str, Any], ...] = (
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


def compose_april_fools_ads(
    content: Sequence[Content],
    now: datetime,
    *,
    mode: str,
    sports_presentation: str,
    pinned_content_id: str,
    rng: random.Random | None = None,
) -> tuple[Content, ...]:
    """Return clean sports content with local April Fools cards when eligible."""

    clean_content = tuple(item for item in content if not is_hardware_ad(item))
    if not _ads_enabled(now, mode, sports_presentation, pinned_content_id):
        return clean_content

    randomizer = random.SystemRandom() if rng is None else rng
    result: list[Content] = []
    visible_count = 0
    ad_index = 0
    brand_pool: list[int] = []
    recent_brands: list[int] = []
    used_copies: set[str] = set()
    for item in clean_content:
        result.append(item)
        if not item.is_shown:
            continue
        visible_count += 1
        if visible_count % AD_INTERVAL != 0:
            continue
        if not brand_pool:
            brand_pool = _random_brand_order(randomizer)
        eligible_brands = [index for index in brand_pool if index not in recent_brands] or brand_pool
        brand_index = randomizer.choice(eligible_brands)
        brand_pool.remove(brand_index)
        result.append(_ad_card(ad_index, randomizer, brand_index, used_copies))
        recent_brands = [*recent_brands, brand_index][-AD_REPEAT_WINDOW:]
        ad_index += 1
    return tuple(result)


def _ads_enabled(
    now: datetime,
    mode: str,
    sports_presentation: str,
    pinned_content_id: str,
) -> bool:
    """Return whether local hardware ads can run for the current display."""

    return (
        now.month == APRIL_FOOLS_MONTH
        and now.day == APRIL_FOOLS_DAY
        and str(mode).strip().lower() == "sports"
        and str(sports_presentation).strip().lower() != "pinned"
        and not str(pinned_content_id or "").strip()
    )


def is_hardware_ad(item: Content) -> bool:
    """Return whether one content item is an old or local campaign card."""

    return (
        item.type.strip().lower() == "fan_duel_joke_ad"
        or str(item.data.get("kind") or "").strip().lower() == "fan_duel_joke_ad"
    )


def _random_brand_order(rng: random.Random) -> list[int]:
    """Return one shuffled brand pool."""

    order = list(range(len(SPORTS_ADS)))
    rng.shuffle(order)
    return order


def _ad_card(
    index: int,
    rng: random.Random,
    brand_index: int,
    used_copies: set[str],
) -> Content:
    """Return one local campaign card with reviewed sourced or parody copy."""

    ad = SPORTS_ADS[brand_index]
    available_spots = tuple(spot for spot in ad["spots"] if str(spot["copy"]) not in used_copies)
    chosen_spot = rng.choice(available_spots or ad["spots"])
    used_copies.add(str(chosen_spot["copy"]))
    data = {
        "id": f"{AD_ID}-{index + 1}",
        "type": "fan_duel_joke_ad",
        "family": "sports",
        "kind": "fan_duel_joke_ad",
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
    }
    return Content(
        id=str(data["id"]),
        type="fan_duel_joke_ad",
        sport="sports",
        data=frozen_mapping(data),
    )


__all__ = ["AD_INTERVAL", "SPORTS_ADS", "compose_april_fools_ads", "is_hardware_ad"]

"""Read live news content through an injected source."""
from __future__ import annotations

import re
import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic
from typing import Callable
from sports_ticker.domain import DisplaySettings
from .background import BackgroundTask
from .http import JsonHttpClient, OwnedClient, PooledJsonHttpClient
from .news_transactions import ConfirmedTransaction, TransactionConfirmationSource
from .source_values import _timeout


_ESPN_NEWS_TYPES = frozenset(("headlinenews",))


_NEWS_RUMOR_MARKERS = re.compile(
    r"\b(?:rumou?rs?|interest(?:ed)?|could|would|might|may|potential|possible|"
    r"explore|consider(?:ing)?|target(?:ing)?|eyeing|monitor(?:ing)?|buzz)\b",
    re.IGNORECASE,
)


_NEWS_TRANSACTION_CANDIDATE = re.compile(
    r"\b(?:trade|trades|traded|trading|acquire|acquires|acquired|"
    r"land|lands|landed|send|sends|sent|transfer|transfers|transferred|"
    r"sign|signs|signed|signing|extension|extend|extends|extended|"
    r"waive|waives|waived|waiver|release|releases|released|"
    r"option|optioned|recall|recalled|activate|activated|reinstated|"
    r"designated|non-tender|suspend|suspended|suspension)\b",
    re.IGNORECASE,
)


_UNVERIFIED_TRANSACTION_KINDS = frozenset(
    ("TRADE", "SIGNING", "EXTENSION", "WAIVER", "DFA", "NO_TENDER", "OPTION", "RECALL", "ACTIVATED", "RELEASE")
)


_NEWS_EXTENSION_MARKER = re.compile(
    r"\b(?:extension|re-?sign(?:s|ed)?|agrees?\s+to\s+.{0,35}\b(?:deal|contract))\b",
    re.IGNORECASE,
)


_NEWS_SIGNING_MARKER = re.compile(
    r"\b(?:sign(?:s|ed)?|agrees?\s+to\s+.{0,35}\bdeal|joins?)\b",
    re.IGNORECASE,
)


_NEWS_INJURY_MARKER = re.compile(
    r"\b(?:injured|will\s+miss|miss(?:es|ed)?|ruled\s+out|out\s+for|"
    r"return\s+from\s+\d+-day\s+il|placed\s+on\s+(?:the\s+)?il|"
    r"undergo(?:ing)?\s+surgery|surgery|concussion|fracture)\b|"
    r"\bbroken\s+(?:bone|finger|wrist|hand|ankle|leg|arm|rib|nose|jaw|"
    r"collarbone|foot|toe|thumb|knee|shoulder|back|neck)\b",
    re.IGNORECASE,
)


_NEWS_WAIVER_MARKER = re.compile(
    r"\b(?:place[sd]?\b.{0,80}\bon\s+waivers?|put\b.{0,80}\bon\s+waivers?|"
    r"claimed\b.{0,80}\boff\s+waivers?|"
    r"clears?\s+waivers?|passes?\s+through\s+waivers?)\b",
    re.IGNORECASE,
)


_NEWS_DFA_MARKER = re.compile(
    r"\b(?:designat(?:e|ed|es|ing)\b.{0,80}\bfor\s+assignment|dfa['’]?d|dfa)\b",
    re.IGNORECASE,
)


_NEWS_RELEASE_MARKER = re.compile(
    r"\b(?:outright\s+released?|released?\s+by|released?\s+from\s+the\s+team|"
    r"cut\s+by)\b",
    re.IGNORECASE,
)


_NEWS_OPTION_MARKER = re.compile(
    r"\b(?:option(?:ed)?\b.{0,80}\bto|sent\b.{0,80}\bto\s+(?:triple|double)-a|outrighted)\b",
    re.IGNORECASE,
)


_NEWS_RECALL_MARKER = re.compile(
    r"\b(?:recall(?:ed)?\b|call(?:ed)?\s+up|promoted\s+from\s+triple-a|returns?\s+to\s+the\s+majors)\b",
    re.IGNORECASE,
)


_NEWS_ACTIVATION_MARKER = re.compile(
    r"\b(?:activat(?:e|ed|es|ing)|reinstat(?:e|ed|es|ing))\b.{0,80}\bfrom\s+(?:the\s+)?(?:\d+-day\s+)?(?:il|injured\s+list)\b",
    re.IGNORECASE,
)


_NEWS_SUSPENSION_MARKER = re.compile(
    r"\b(?:suspend(?:ed|s|ing)?|suspension)\b",
    re.IGNORECASE,
)


_NEWS_RETIREMENT_MARKER = re.compile(
    r"\b(?:retires?|retirement|calls?\s+it\s+a\s+career)\b",
    re.IGNORECASE,
)


_NEWS_NO_TENDER_MARKER = re.compile(
    r"\b(?:non[- ]tender(?:ed)?|no[- ]tender(?:ed)?)\b",
    re.IGNORECASE,
)


class EspnNewsSource:
    """Read followed-team ESPN headlines without blocking scoreboard refreshes."""

    def __init__(
        self,
        news_urls: Mapping[str, str],
        client: JsonHttpClient | None = None,
        *,
        team_color_lookup: Callable[[str], Mapping[str, Mapping[str, str]]] | None = None,
        transaction_confirmation_source: TransactionConfirmationSource | None = None,
        timeout: float = 10.0,
        refresh_seconds: float = 30.0,
        background: bool = True,
    ) -> None:
        self._news_urls = dict(news_urls)
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self._client = self._client_owner.client
        self._owned_dependencies = []
        self._worker = BackgroundTask(self._close_resources, thread_factory=lambda **kwargs: Thread(**kwargs))
        self._team_color_lookup = team_color_lookup
        self._transaction_confirmation_source = transaction_confirmation_source
        self._timeout = _timeout(timeout)
        self._refresh_seconds = _timeout(refresh_seconds)
        self._background = bool(background)
        self._cache: tuple[dict[str, object], ...] = ()
        self._last_started: dict[tuple[str, ...], float] = {}
        self._refreshing: set[tuple[str, ...]] = set()
        self._lock = Lock()

    def own_dependency(self, resource) -> None:
        self._owned_dependencies.append(resource)

    def _close_resources(self) -> None:
        errors = []
        for resource in (self._client_owner, *self._owned_dependencies):
            try:
                resource.close()
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]

    def close(self) -> None:
        self._worker.close()

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        """Return cached followed-team headlines and refresh them outside polling."""

        if settings.mode != "sports":
            return {"news": []}
        followed = tuple(sorted({str(value).strip().lower() for value in settings.my_teams if str(value).strip()}))
        if self._background:
            self._start_refresh()
            with self._lock:
                records = self._cache
        else:
            records = self._fetch_news()
        return {"news": list(_filter_news_for_ticker(records, set(followed)))}

    def _start_refresh(self) -> None:
        now = monotonic()
        with self._lock:
            cache_key = ("all",)
            if cache_key in self._refreshing or now - self._last_started.get(cache_key, float("-inf")) < self._refresh_seconds:
                return
            self._last_started[cache_key] = now
            self._refreshing.add(cache_key)
        if not self._worker.start(self._refresh, name="ticker-news-refresh"):
            with self._lock:
                self._refreshing.discard(("all",))

    def _refresh(self) -> None:
        try:
            records = self._fetch_news()
            with self._lock:
                self._cache = records
        finally:
            with self._lock:
                self._refreshing.discard(("all",))

    def _fetch_news(self) -> tuple[dict[str, object], ...]:
        records: list[dict[str, object]] = []
        for league, url in self._news_urls.items():
            try:
                payload = self._client.get_json(url, timeout=self._timeout)
            except Exception:
                continue
            articles = payload.get("articles", ()) if isinstance(payload, Mapping) else ()
            if not isinstance(articles, Sequence) or isinstance(articles, (str, bytes)):
                continue
            league_records: list[dict[str, object]] = []
            for article in articles:
                confirmed_transaction = None
                if (
                    self._transaction_confirmation_source is not None
                    and isinstance(article, Mapping)
                    and _NEWS_TRANSACTION_CANDIDATE.search(
                        f"{article.get('headline') or article.get('title') or ''} "
                        f"{article.get('description') or ''}"
                    )
                ):
                    try:
                        article_text = (
                            f"{article.get('headline') or article.get('title') or ''} "
                            f"{article.get('description') or ''}"
                        )
                        confirmed_transaction = self._transaction_confirmation_source.confirm_transaction(
                            league,
                            _article_athletes(article),
                            tuple(abbr for abbr, _name in _article_team_records(article)),
                            article_text,
                            now=datetime.now(timezone.utc),
                        )
                    except Exception:
                        confirmed_transaction = None
                record = _classify_espn_news_article(
                    article,
                    league,
                    set(),
                    confirmed_transaction=confirmed_transaction,
                )
                if record is None:
                    continue
                article_id = str(record.pop("source_id"))
                identifier = hashlib.sha1(f"{league}:{article_id}".encode()).hexdigest()[:20]
                record["id"] = identifier
                record.pop("source_headline", None)
                league_records.append(record)
            if league_records and self._team_color_lookup is not None:
                try:
                    team_colors = self._team_color_lookup(league)
                except Exception:
                    team_colors = {}
                if isinstance(team_colors, Mapping):
                    for record in league_records:
                        _apply_news_team_colors(record, team_colors)
            records.extend(league_records)
        return tuple(records[:24])


def _apply_news_team_colors(
    record: dict[str, object],
    team_colors: Mapping[str, Mapping[str, str]],
) -> None:
    """Attach catalog colors to the teams shown by one news banner."""

    for side in ("from", "to"):
        abbreviation = str(record.get(f"{side}_abbr") or "").strip().upper()
        team = team_colors.get(abbreviation)
        if not isinstance(team, Mapping):
            continue
        for color_key, field_suffix in (
            ("color", "color"),
            ("alt_color", "alt_color"),
        ):
            value = str(team.get(color_key) or "").strip().lstrip("#")
            if len(value) != 6:
                continue
            try:
                for index in (0, 2, 4):
                    int(value[index:index + 2], 16)
            except ValueError:
                continue
            record[f"{side}_{field_suffix}"] = f"#{value.upper()}"


def _filter_news_for_ticker(
    records: Sequence[Mapping[str, object]],
    followed: set[str],
) -> tuple[Mapping[str, object], ...]:
    """Broadcast blockbusters and keep other sports news on followed teams."""

    visible: list[Mapping[str, object]] = []
    for record in records:
        if str(record.get("distribution") or "followed_teams") == "global":
            visible.append(record)
            continue
        sport = str(record.get("sport") or "").strip().casefold()
        teams = record.get("teams")
        if not isinstance(teams, Sequence) or isinstance(teams, (str, bytes)):
            continue
        if any(f"{sport}:{str(team).strip().casefold()}" in followed for team in teams):
            visible.append(record)
    return tuple(visible)


def _article_team_records(article: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """Return explicit ESPN team abbreviations in source order."""

    categories = article.get("categories")
    if not isinstance(categories, Sequence) or isinstance(categories, (str, bytes)):
        return ()
    teams: list[tuple[str, str]] = []
    seen: set[str] = set()
    for category in categories:
        if not isinstance(category, Mapping) or str(category.get("type") or "").lower() != "team":
            continue
        team = category.get("team")
        team_data = team if isinstance(team, Mapping) else {}
        abbreviation = str(
            team_data.get("abbreviation")
            or category.get("abbreviation")
            or ""
        ).strip().upper()
        if not 2 <= len(abbreviation) <= 4 or not abbreviation.isalnum() or abbreviation in seen:
            continue
        name = str(
            team_data.get("displayName")
            or team_data.get("shortDisplayName")
            or category.get("description")
            or abbreviation
        ).strip()
        teams.append((abbreviation, name))
        seen.add(abbreviation)
    return tuple(teams)


def _article_athletes(article: Mapping[str, object]) -> tuple[str, ...]:
    """Return explicit ESPN athlete names without guessing from article text."""

    categories = article.get("categories")
    if not isinstance(categories, Sequence) or isinstance(categories, (str, bytes)):
        return ()
    athletes: list[str] = []
    seen: set[str] = set()
    for category in categories:
        if not isinstance(category, Mapping) or str(category.get("type") or "").lower() != "athlete":
            continue
        athlete = category.get("athlete")
        athlete_data = athlete if isinstance(athlete, Mapping) else {}
        name = str(
            athlete_data.get("displayName")
            or athlete_data.get("shortName")
            or category.get("description")
            or ""
        ).strip()
        key = name.casefold()
        if name and key not in seen:
            athletes.append(name)
            seen.add(key)
    return tuple(athletes)


def _classify_espn_news_article(
    article: object,
    league: str,
    followed: set[str],
    *,
    confirmed_transaction: ConfirmedTransaction | None = None,
) -> dict[str, object] | None:
    """Build one conservative sports-news record or reject the article."""

    if not isinstance(article, Mapping):
        return None
    article_type = str(article.get("type") or "").strip().lower()
    if article_type not in _ESPN_NEWS_TYPES:
        return None
    headline = str(article.get("headline") or article.get("title") or "").strip()
    description = str(article.get("description") or "").strip()
    if not headline:
        return None
    searchable = f"{headline} {description}"
    if _NEWS_RUMOR_MARKERS.search(searchable) and confirmed_transaction is None:
        return None
    teams = _article_team_records(article)
    athletes = _article_athletes(article)
    if not teams or not athletes:
        return None
    if followed and not any(
        f"{league}:{abbreviation.casefold()}" in followed
        for abbreviation, _name in teams
    ):
        return None

    kind = ""
    from_abbr = ""
    to_abbr = teams[0][0]
    compact_prefix = ""
    transaction_candidate = bool(_NEWS_TRANSACTION_CANDIDATE.search(searchable))
    if confirmed_transaction is not None:
        kind = confirmed_transaction.kind.upper()
        from_abbr = confirmed_transaction.from_abbr
        to_abbr = confirmed_transaction.to_abbr
        compact_prefix = "ACQUIRE" if kind == "TRADE" else kind
    elif _NEWS_WAIVER_MARKER.search(headline):
        kind = "WAIVER"
        compact_prefix = "WAIVER"
    elif _NEWS_DFA_MARKER.search(headline):
        kind = "DFA"
        compact_prefix = "DFA"
    elif _NEWS_NO_TENDER_MARKER.search(headline):
        kind = "NO_TENDER"
        compact_prefix = "NON-TENDER"
    elif _NEWS_ACTIVATION_MARKER.search(headline):
        kind = "ACTIVATED"
        compact_prefix = "ACTIVE"
    elif _NEWS_RECALL_MARKER.search(headline):
        kind = "RECALL"
        compact_prefix = "RECALL"
    elif _NEWS_OPTION_MARKER.search(headline):
        kind = "OPTION"
        compact_prefix = "OPTION"
    elif _NEWS_SUSPENSION_MARKER.search(headline):
        kind = "SUSPENSION"
        compact_prefix = "SUSPEND"
    elif _NEWS_RETIREMENT_MARKER.search(headline):
        kind = "RETIREMENT"
        compact_prefix = "RETIRE"
    elif _NEWS_RELEASE_MARKER.search(headline):
        kind = "RELEASE"
        compact_prefix = "RELEASE"
    elif _NEWS_EXTENSION_MARKER.search(headline):
        kind = "EXTENSION"
        compact_prefix = "EXTENSION"
    elif _NEWS_SIGNING_MARKER.search(headline):
        kind = "SIGNING"
        compact_prefix = "SIGN"
    elif _NEWS_INJURY_MARKER.search(headline):
        kind = "INJURY"
        compact_prefix = "STATUS"
    elif transaction_candidate:
        kind = "NEWS"
        compact_prefix = ""
    else:
        return None

    if kind in _UNVERIFIED_TRANSACTION_KINDS and confirmed_transaction is None:
        kind = "NEWS"
        compact_prefix = ""
    display_teams = (
        tuple((abbr, abbr) for abbr in (from_abbr, to_abbr) if abbr)
        if confirmed_transaction is not None
        else teams
    )
    impact_text = (
        f"{searchable} {confirmed_transaction.details}"
        if confirmed_transaction is not None
        else searchable
    )
    impact_score, impact_tier = _news_impact(impact_text, kind, display_teams)
    names = " + ".join(athletes[:2])
    if len(athletes) > 2:
        names += " + ..."
    text = headline if kind == "NEWS" else f"{compact_prefix} {names}".strip()
    return {
        "kind": kind,
        "domain": "sports",
        "sport": league,
        "from_abbr": from_abbr,
        "to_abbr": to_abbr,
        "from_color": "#8B93A3",
        "to_color": "#8B93A3",
        "text": text,
        "teams": [abbreviation for abbreviation, _name in display_teams],
        "athletes": list(athletes),
        "impact_score": impact_score,
        "impact_tier": impact_tier,
        "distribution": "global"
        if kind == "TRADE" and impact_tier in {"BLOCKBUSTER", "MAJOR"}
        else "followed_teams",
        "verification": (
            "source_report"
            if confirmed_transaction is None
            else "official_nhl_trade_tracker"
            if confirmed_transaction.kind.upper() == "TRADE"
            else "official_league_transaction"
        ),
        "source_headline": headline,
        "source_id": str(article.get("id") or article.get("link") or headline),
        "source_url": str(
            ((article.get("links") or {}).get("web") or {}).get("href")
            if isinstance(article.get("links"), Mapping)
            and isinstance((article.get("links") or {}).get("web"), Mapping)
            else ""
        ),
        "published_at": str(article.get("published") or article.get("lastModified") or ""),
        "transaction_at": (
            confirmed_transaction.occurred_at.isoformat()
            if confirmed_transaction is not None
            else ""
        ),
        "transaction_source_url": (
            confirmed_transaction.source_url
            if confirmed_transaction is not None
            else ""
        ),
    }


def _news_impact(
    searchable: str,
    kind: str,
    teams: Sequence[tuple[str, str]],
) -> tuple[int, str]:
    """Score confirmed transaction scope from source language and structure."""

    if kind != "TRADE":
        return 0, "NORMAL"
    text = searchable.casefold()
    score = 0
    if re.search(r"\b(?:blockbuster|gargantuan|franchise[- ]changing|superstar|all-world)\b", text):
        score += 40
    if re.search(r"\b(?:mvp|cy young|all-star|all-pro|all nba|all-nba|champion|captain)\b", text):
        score += 30
    if re.search(r"\b(?:two-time|three-time|four-time|five-time|six-time|ten-time|former)\b", text):
        score += 10
    if re.search(r"\b(?:highest-paid|record-setting)\b|\$\s*\d{2,3}\s*million\b|\b\d+[- ]year,?\s*\$\s*\d{2,3}\s*million\b", text):
        score += 15
    if re.search(r"\b(?:\d+\s+first-round|\d+(?:st|nd|rd|th)[- ]round|multiple\s+first-round|top prospect|prospect haul|massive haul|big prospect haul)\b", text):
        score += 15
    if re.search(r"\b(?:no\.\s*1 overall|cornerstone)\b", text):
        score += 15
    if re.search(r"\b(?:\d+[- ]player|\d+[- ]team|multi-team|three-team|four-team|seven-team)\b", text):
        score += 10
    if len(teams) >= 3:
        score += 5
    if score >= 60:
        return min(score, 100), "BLOCKBUSTER"
    if score >= 25:
        return min(score, 100), "MAJOR"
    return min(score, 100), "NORMAL"


def _article_abbreviations(article: Mapping[str, object]) -> tuple[str, ...]:
    """Collect explicit ESPN team abbreviations without guessing from prose."""

    teams = _article_team_records(article)
    if teams:
        return tuple(abbreviation for abbreviation, _name in teams)

    values: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in {"abbreviation", "abbrev", "shortname", "short_name"}:
                    text = str(child or "").strip().upper()
                    if 2 <= len(text) <= 4 and text.isalnum():
                        values.add(text)
                visit(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child)

    visit(article)
    return tuple(sorted(values))


__all__ = ['EspnNewsSource']

"""Resolve NCAA school logos and college football rankings for ESPN events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from types import MappingProxyType
from typing import Any

from ticker.shared.leagues import COLLEGE_FOOTBALL_LEAGUES

from ticker.shared.payloads import as_mapping as _mapping, as_sequence as _sequence, first_mapping as _first_mapping
from ticker.shared.sports_display import (
    normalize_rank,
)
from ticker.server.providers.espn_events import _competitors, _normalize_team_name, _team_name_candidates, _team_source_logo


_NCAA_COLLEGE_FOOTBALL_RANKING_URLS = MappingProxyType(
    {
        "ncf_fbs": "https://ncaa-api.henrygd.me/rankings/football/fbs/associated-press",
        "ncf_fcs": "https://ncaa-api.henrygd.me/rankings/football/fcs/stats-perform-fcs-top-25",
    }
)


def _needs_ncaa_logo_lookup(
    active_leagues: Sequence[tuple[str, str]],
    events_by_league: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool:
    """Return whether an active college football event lacks an ESPN logo."""

    for league, _url in active_leagues:
        if league not in COLLEGE_FOOTBALL_LEAGUES:
            continue
        for event in events_by_league.get(league, ()):
            competition = _first_mapping(event.get("competitions"))
            for competitor in _competitors(competition.get("competitors")):
                source = _mapping(competitor.get("team"))
                if not _team_source_logo(source) and _team_name_candidates(source):
                    return True
    return False


def _parse_ncaa_school_index(payload: Any) -> dict[str, str]:
    """Map unique NCAA school names to logo slugs."""

    records = _sequence(payload)
    candidates: dict[str, set[str]] = {}
    for record in records:
        source = _mapping(record)
        slug = str(source.get("slug") or "").strip()
        if not slug:
            continue
        for value in (source.get("name"), source.get("long"), slug):
            key = _normalize_team_name(value)
            if key:
                candidates.setdefault(key, set()).add(slug)
    return {
        key: next(iter(slugs))
        for key, slugs in candidates.items()
        if len(slugs) == 1
    }


_COLLEGE_RANKING_NAME_ALIASES = MappingProxyType(
    {
        "southern cal": "usc",
        "southern california": "usc",
        "miami fl": "miami",
        "miami florida": "miami",
        "pitt": "pittsburgh",
        "uconn": "connecticut",
    }
)


def _parse_ncaa_college_football_rankings(payload: Any) -> dict[str, str]:
    """Map NCAA ranking rows to normalized school names."""

    result: dict[str, str] = {}
    for entry in _sequence(_mapping(payload).get("data")):
        source = _mapping(entry)
        rank = normalize_rank(source.get("RANK"))
        if not rank:
            continue
        for key in _college_ranking_name_keys(source.get("SCHOOL")):
            result.setdefault(key, rank)
    return result


def _college_ranking_name_keys(value: Any) -> tuple[str, ...]:
    """Return conservative NCAA and ESPN school-name keys for one ranking row."""

    text = re.sub(r"\s*\(\d+\)\s*$", "", str(value or ""))
    normalized = _normalize_team_name(text)
    if not normalized:
        return ()
    words = normalized.split()
    if words[-1] == "st":
        words[-1] = "state"
    normalized = " ".join(words)
    alias = _COLLEGE_RANKING_NAME_ALIASES.get(normalized)
    return tuple(dict.fromkeys(key for key in (normalized, alias) if key))


def _resolve_college_football_rankings(
    rankings: Mapping[str, Mapping[str, str]],
    events_by_league: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, str]:
    """Resolve both NCAA polls to ESPN team IDs carried by scoreboard events."""

    resolved: dict[str, str] = {}
    college_events = tuple(
        event
        for league in _NCAA_COLLEGE_FOOTBALL_RANKING_URLS
        for event in events_by_league.get(league, ())
    )
    for league, name_rankings in rankings.items():
        if league not in _NCAA_COLLEGE_FOOTBALL_RANKING_URLS:
            continue
        for event in college_events:
            competition = _first_mapping(event.get("competitions"))
            for competitor in _competitors(competition.get("competitors")):
                team = _mapping(competitor.get("team"))
                team_id = str(team.get("id") or competitor.get("id") or "").strip()
                if not team_id:
                    continue
                rank = next(
                    (
                        name_rankings[key]
                        for candidate in _team_name_candidates(team)
                        for key in _college_ranking_name_keys(candidate)
                        if key in name_rankings
                    ),
                    "",
                )
                if rank:
                    resolved.setdefault(team_id, rank)
    return resolved

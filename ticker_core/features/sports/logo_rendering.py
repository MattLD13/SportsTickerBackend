"""Own native sports logo preparation and placement."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from ticker_core.assets.model import LogoAssetView
from ticker_core.assets.processors import prepare_contained, prepare_contained_native_grid


SCROLLING_TEAM_LOGO_SIZE = 22
FULL_TEAM_LOGO_SIZE = 24
FULL_FOOTBALL_TEAM_LOGO_SIZE = 20


@dataclass(frozen=True, slots=True)
class TeamLogoLayout:
    """Describe the asset request and normal native logo placement."""

    request_size: tuple[int, int]
    size: int
    x: int
    y: int


def team_logo_layout(view: str, sport: str = "") -> TeamLogoLayout:
    """Return native dimensions for scrolling or full-screen sports."""
    if view == "scrolling":
        return TeamLogoLayout((22, 22), SCROLLING_TEAM_LOGO_SIZE, 1, 9)
    if view != "full_screen":
        raise ValueError("Ticker layout must be full_screen or scrolling.")
    sport = sport.lower()
    if any(value in sport for value in ("football", "nfl", "ncf")):
        return TeamLogoLayout((24, 24), FULL_FOOTBALL_TEAM_LOGO_SIZE, 6, 6)
    x = 6 if any(value in sport for value in ("baseball", "mlb", "soccer")) else 8
    return TeamLogoLayout((24, 24), FULL_TEAM_LOGO_SIZE, x, 4)


def resize_team_logo(logo: Image.Image, size: int) -> Image.Image:
    """Apply the same final resize used by the full-screen renderer."""
    resized = logo if logo.size == (size, size) else logo.resize((size, size), Image.Resampling.LANCZOS)
    for attribute in ("logo_rendering_outline", "logo_rendering_cutoff"):
        if hasattr(logo, attribute):
            setattr(resized, attribute, getattr(logo, attribute))
    return resized


def prepare_team_logo(raw: bytes, layout: TeamLogoLayout, *, method: str = "old") -> Image.Image:
    """Prepare original bytes through one selected logo filtering method."""
    if method == "old":
        prepared = prepare_contained(raw, layout.request_size)
    elif method == "new":
        prepared = prepare_contained_native_grid(raw, layout.request_size)
    else:
        raise ValueError("Logo rendering method must be old or new.")
    return resize_team_logo(prepared, layout.size)


def get_prepared_team_logo(logos, url: str | None, size: tuple[int, int], rendering=None):
    """Read one team logo with its selected rendering and outline settings."""
    if not url:
        return None
    if isinstance(logos, LogoAssetView):
        return logos.get(url, size, rendering)
    return logos.get(url, size)

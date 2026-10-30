"""Place team logos so they stay readable, and draw a team badge when a logo is missing.

A logo that blends into the pixels below it gets a one-pixel keyline. A logo with a selected
rendering can ask for an inner outline instead: "inner" always, "auto" when its edge is dark.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ticker_core.assets.model import LogoAssetView
from ticker_core.assets.processors import prepare_contained, prepare_contained_native_grid

from ..palette import relative_luminance
from ..text import draw_hybrid, plain_text

PANE_LOGO, FULL_LOGO, FULL_FOOTBALL_LOGO = 22, 24, 20
ALPHA = 160
CONTRAST_RATIO = 2.0
KEYLINES = ((244, 247, 250), (8, 12, 18))
NEIGHBORS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
BADGE_SCALE = 4


class Outline(str, Enum):
    """The keyline policy: the pane needs less contrast than the pinned panel."""

    SCROLL = "scroll"
    FULL = "full"


# The share of the logo that must contrast with the pixels below, and the color distance that counts as contrast.
POLICY = {Outline.SCROLL: (0.20, 12 * 12), Outline.FULL: (0.25, 32 * 32)}


@dataclass(frozen=True, slots=True)
class TeamLogoLayout:
    """The asset request size, the drawn size, and the normal position of one team logo."""

    request_size: tuple[int, int]
    size: int
    x: int
    y: int


def team_logo_layout(view: str, sport: str = "") -> TeamLogoLayout:
    if view == "scrolling":
        return TeamLogoLayout((22, 22), PANE_LOGO, 1, 9)
    if view != "full_screen":
        raise ValueError("Ticker layout must be full_screen or scrolling.")
    sport = sport.lower()
    if any(word in sport for word in ("football", "nfl", "ncf")):
        return TeamLogoLayout((24, 24), FULL_FOOTBALL_LOGO, 6, 6)
    return TeamLogoLayout((24, 24), FULL_LOGO, 6 if any(word in sport for word in ("baseball", "mlb", "soccer")) else 8, 4)


def prepare_team_logo(raw: bytes, layout: TeamLogoLayout, *, method: str = "old") -> Image.Image:
    """Prepare original logo bytes with the old or the new filter, at the drawn size."""
    if method == "old":
        prepared = prepare_contained(raw, layout.request_size)
    elif method == "new":
        prepared = prepare_contained_native_grid(raw, layout.request_size)
    else:
        raise ValueError("Logo rendering method must be old or new.")
    resized = prepared if prepared.size == (layout.size,) * 2 else prepared.resize((layout.size,) * 2, Image.Resampling.LANCZOS)
    for name in ("logo_rendering_outline", "logo_rendering_cutoff"):
        if hasattr(prepared, name):
            setattr(resized, name, getattr(prepared, name))
    return resized


def team_logo(logos, url: str | None, size: tuple[int, int], rendering=None) -> Image.Image | None:
    """Read one prepared team logo with its selected rendering."""
    if not url:
        return None
    return logos.get(url, size, rendering) if isinstance(logos, LogoAssetView) else logos.get(url, size)


def paste_team_logo(canvas: Image.Image, logo: Image.Image, xy: tuple[int, int], *, outline: Outline = Outline.SCROLL) -> bool:
    """Paste a logo with the keyline policy of its view. Return True when the logo got a keyline or an outline."""
    mark = logo.convert("RGBA")
    x, y = int(xy[0]), int(xy[1])
    selected = getattr(logo, "logo_rendering_outline", None)
    if selected in {"off", "inner", "auto"}:
        cutoff = float(getattr(logo, "logo_rendering_cutoff", 0.0))
        outlined = selected == "inner" or (selected == "auto" and mean_edge_brightness(mark) <= cutoff)
        canvas.paste(mark, (x, y), mark)
        if outlined:
            canvas.paste(Image.new("RGBA", mark.size, (244, 247, 250, 255)), (x, y), _inner_contour(mark))
        return outlined
    fraction, distance = POLICY[Outline(outline)]
    below = canvas.crop((x, y, x + mark.width, y + mark.height)).convert("RGBA")
    edges, pixels = _pairs(mark, below, edges_only=True), _pairs(mark, below, edges_only=False)
    keyline = bool(edges and pixels and _blends(edges, fraction, distance) and _blends(pixels, fraction, distance))
    if keyline:
        line = Image.new("RGBA", mark.size, (*_keyline_color(edges), 255))
        canvas.paste(line, (x, y), mark.getchannel("A").filter(ImageFilter.MaxFilter(3)))
    canvas.paste(mark, (x, y), mark)
    return keyline


def mean_edge_brightness(mark: Image.Image) -> float:
    """Return the mean brightness of the visible logo edge."""
    pairs = _pairs(mark.convert("RGBA"), Image.new("RGBA", mark.size, (0, 0, 0, 255)), edges_only=True)
    if not pairs:
        return 255.0
    return sum(0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] for color, _ in pairs) / len(pairs)


def draw_missing_team_badge(image: Image.Image, xy: tuple[int, int], size: int, team_color: Sequence[int] | None,
                            abbreviation: object) -> None:
    """Draw a rounded team-color badge with the team code where a logo is missing."""
    if size < 8:
        return
    x, y = int(xy[0]), int(xy[1])
    color = _rgb(team_color)
    text = (250, 252, 255, 255) if relative_luminance(color) < 0.18 else (8, 12, 18, 255)
    inset = max(1, size // 16)
    radius = max(1, round((size - 2 * inset) * 0.22))
    # The mask draws at four times the size and shrinks, so the corners are smooth.
    mask = Image.new("L", (size * BADGE_SCALE, size * BADGE_SCALE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((inset * BADGE_SCALE, inset * BADGE_SCALE, (size - inset) * BADGE_SCALE - 1,
                                            (size - inset) * BADGE_SCALE - 1), radius=radius * BADGE_SCALE, fill=255)
    image.paste(Image.new("RGBA", (size, size), (*color, 255)), (x, y), mask.resize((size, size), Image.Resampling.LANCZOS))
    label = _badge_label(abbreviation)
    step = 4 if len(label) == 4 else 5
    text_x = x + max(0, (size - ((len(label) - 1) * step + 4)) // 2)
    draw = ImageDraw.Draw(image, "RGBA")
    for index, character in enumerate(label):
        draw_hybrid(draw, text_x + index * step, y + (size - 6) // 2, character, text)


def _badge_label(value: object) -> str:
    compact = "".join(char for char in plain_text(str(value or "")).strip().upper() if char.isalnum() or char in "-&")
    return compact[:4] or "?"


def _rgb(color: Sequence[int] | None) -> tuple[int, int, int]:
    try:
        channels = tuple(max(0, min(255, int(channel))) for channel in color[:3]) if color else ()
    except (TypeError, ValueError):
        channels = ()
    return channels if len(channels) == 3 else (86, 104, 132)


def _inner_contour(mark: Image.Image) -> Image.Image:
    """Return the silhouette boundary one opaque pixel inside the mark."""
    silhouette = mark.getchannel("A").point(lambda value: 255 if value >= ALPHA else 0)
    padded = Image.new("L", (mark.width + 2, mark.height + 2), 0)
    padded.paste(silhouette, (1, 1))
    eroded = padded.filter(ImageFilter.MinFilter(3)).crop((1, 1, mark.width + 1, mark.height + 1))
    return ImageChops.subtract(silhouette, eroded)


def _pairs(mark: Image.Image, below: Image.Image, *, edges_only: bool):
    """Return (logo color, color below) for each opaque logo pixel, or for each opaque edge pixel."""
    width, height = mark.size
    marks, unders = mark.load(), below.load()
    pairs = []
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = marks[x, y]
            if alpha < ALPHA or (edges_only and not _edge(marks, x, y, width, height)):
                continue
            under = unders[x, y]
            pairs.append(((red, green, blue), (under[0], under[1], under[2])))
    return pairs


def _edge(pixels, x: int, y: int, width: int, height: int) -> bool:
    """Return True when an opaque pixel touches transparency or the image edge."""
    for dx, dy in NEIGHBORS:
        nx, ny = x + dx, y + dy
        if nx < 0 or nx >= width or ny < 0 or ny >= height or pixels[nx, ny][3] < ALPHA:
            return True
    return False


def _blends(pairs, fraction: float, distance: int) -> bool:
    """Return True when too small a share of the pairs contrast."""
    return sum(1 for mark, below in pairs if _contrasts(mark, below, distance)) / len(pairs) < fraction


def _contrasts(mark, below, distance: int) -> bool:
    lighter, darker = sorted((relative_luminance(mark), relative_luminance(below)), reverse=True)
    if (lighter + 0.05) / (darker + 0.05) >= CONTRAST_RATIO:
        return True
    return sum((mark[channel] - below[channel]) ** 2 for channel in range(3)) >= distance


def _keyline_color(edges) -> tuple[int, int, int]:
    """Choose the light or dark keyline that differs most from both the logo edge and the pixels below."""
    count = len(edges)
    mark = tuple(sum(pair[0][channel] for pair in edges) // count for channel in range(3))
    below = tuple(sum(pair[1][channel] for pair in edges) // count for channel in range(3))

    def score(candidate):
        return min(max(abs(candidate[channel] - mark[channel]) for channel in range(3)),
                   max(abs(candidate[channel] - below[channel]) for channel in range(3)))

    return max(KEYLINES, key=score)

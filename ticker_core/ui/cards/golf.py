"""Draw golf: a top-three pane, an 18-hole pinned scoreboard, and team match play."""
from __future__ import annotations

import re
from typing import Any

from PIL import Image, ImageDraw

from ..frame import ContentScene, ItemKey, RenderContext, RenderedContent
from ..layers import ImageTemplates
from ..text import GOLF_FONT, FontSet, clean_text, draw_hybrid, draw_tiny

WIDTH, HEIGHT = 384, 32
PAGE_SECONDS = 4.0
DEFAULT_PARS = [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4]
HOLE_X, HOLE_STEP, HOLE_WIDTH = 58, 14, 9
ROWS = (14, 20, 26)
HEADER_TEXT, HEADER_SHADOW, RULE, LABEL = (255, 240, 150, 255), (8, 8, 8, 180), (55, 76, 130), (80, 95, 130)
TEAM_NAMES = {"USA": "US", "UNITED STATES": "US", "INTL": "INT", "INTERNATIONAL": "INT"}
PALETTES = {
    "masters": {
        "bg": (0, 14, 8, 255), "gold": (231, 199, 92, 255), "eagle": (231, 199, 92, 255), "birdie": (164, 225, 155, 255),
        "bogey": (241, 139, 119, 255), "double": (170, 67, 65, 255), "par": (145, 169, 145, 255), "white": (244, 248, 231, 255),
        "black": (0, 39, 27, 255), "label": (145, 169, 145, 255), "accent": (231, 199, 92, 255), "active": (231, 199, 92, 255),
        "idle": (24, 50, 33, 255),
    },
    "pga": {
        "bg": (0, 0, 0, 255), "gold": (235, 196, 83, 255), "eagle": (235, 196, 83, 255), "birdie": (68, 211, 128, 255),
        "bogey": (240, 103, 103, 255), "double": (157, 43, 67, 255), "par": (112, 124, 136, 255), "white": (241, 246, 250, 255),
        "black": (0, 0, 0, 255), "label": (112, 124, 136, 255), "accent": (91, 171, 221, 255), "active": (91, 171, 221, 255),
        "idle": (25, 30, 35, 255),
    },
}


class GolfCard:
    def __init__(self, fonts: FontSet) -> None:
        self._key = ItemKey("golf")
        self._panes = ImageTemplates()

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        # The pinned board turns a page every four seconds.
        pinned = str(scene.item.get("sports_presentation", "")).lower() == "pinned"
        return self._key(scene, asset_revision, int(max(0.0, scene.elapsed) // 4.0) if pinned else None)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        item = scene.item if isinstance(scene.item, dict) else {}
        if item.get("sports_presentation") == "pinned":
            return RenderedContent(self.full(item, scene.elapsed))
        return RenderedContent(self.pane(item))

    # The pane in the scrolling strip

    def pane(self, item: dict[str, Any]) -> Image.Image:
        golf = _golf(item)
        if golf.get("format") == "match_play":
            return self._match_pane(golf)
        event = str(golf.get("event_name") or item.get("away_abbr") or "PGA TOUR").upper()
        number = re.search(r"\d+", str(golf.get("round") or item.get("status") or "").upper())
        header = f"{event} R{number.group() if number else '-'}"
        width = max(128, len(header) * 5 + 4)
        today_x, total_x = width - 55, width - 27

        def layer() -> Image.Image:
            image, draw = _pane_header(width, header)
            draw_tiny(draw, today_x, 8, "TODAY", LABEL)
            draw_tiny(draw, total_x, 8, "TOTAL", LABEL)
            return image

        image = self._panes.render((width, header), layer)
        draw = ImageDraw.Draw(image)
        players = _players(golf)[:3]
        pars = golf.get("pars", []) if isinstance(golf.get("pars"), list) else []
        if not players:
            draw_tiny(draw, 18, 18, "LOADING", (150, 150, 150))
            return image
        name_chars = max(8, (today_x - 20) // 5)
        for y, player in zip(ROWS, players):
            position = str(player["pos"])[:3]
            parts = str(player["name"]).split()
            name = (f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else str(player["name"])).upper()[:name_chars]
            today = _today(player, pars) if _started(player) else None
            today_text, total_text = _score(today), _score(player["total"])
            draw_tiny(draw, 1, y, position, (255, 215, 0) if position.replace("T", "") == "1"
                      else (220, 80, 80) if position == "CUT" else (200, 200, 200))
            draw_tiny(draw, 18, y, name, "white")
            draw_tiny(draw, width - 43 - len(today_text) * 5 // 2, y, today_text, _pane_score_color(today))
            draw_tiny(draw, width - 15 - len(total_text) * 5 // 2, y, total_text, _pane_score_color(player["total"]))
        return image

    def _match_pane(self, golf: dict[str, Any]) -> Image.Image:
        first, second = _teams(golf)
        title = (f"{golf.get('event_name') or 'TEAM GOLF'}  {_team(first.get('abbr', 'USA'))} {first.get('score', '--')}  "
                 f"{_team(second.get('abbr', 'INTL'))} {second.get('score', '--')}").upper()
        rows = []
        for match in _matches(golf)[:3]:
            if isinstance(match, dict):
                left, right = _sides(match)
                result, winner = _result(left, right)
                rows.append((f"{_side_name(left, 'USA')} / {_side_name(right, 'INTL')}", result, winner))
        result_width = max([30, *(len(result) * 5 for _, result, _ in rows)])
        width = max(128, len(title) * 5 + 4, max((len(label) for label, _, _ in rows), default=8) * 5 + result_width + 22)
        result_x = width - result_width - 2

        def layer() -> Image.Image:
            image, draw = _pane_header(width, title)
            draw_tiny(draw, 18, 8, "MATCH", LABEL)
            draw_tiny(draw, result_x + (result_width - len("RESULT") * 5) // 2, 8, "RESULT", LABEL)
            return image

        image = self._panes.render((width, title, result_width, "match"), layer)
        draw = ImageDraw.Draw(image)
        for y, (label, result, winner) in zip(ROWS, rows):
            draw_tiny(draw, 1, y, label, "white")
            draw_tiny(draw, result_x + (result_width - len(result) * 5) // 2, y, result, (255, 215, 0) if winner else (150, 150, 150))
        return image

    # The pinned panel

    def full(self, item: dict[str, Any], elapsed: float) -> Image.Image:
        golf = _golf(item)
        colors = PALETTES["masters" if str(golf.get("brand", "pga")).lower() == "masters" else "pga"]
        image = Image.new("RGBA", (WIDTH, HEIGHT), colors["bg"])
        draw = ImageDraw.Draw(image)
        if golf.get("format") == "match_play":
            _match_full(draw, golf, colors, elapsed)
            return image
        pars = golf.get("pars", []) if isinstance(golf.get("pars"), list) else []
        pars = (pars + DEFAULT_PARS)[:18]
        players = _players(golf)
        page = _page(elapsed, max(1, min(5, (len(players) + 2) // 3)))
        _text(draw, "MASTERS R3" if str(golf.get("brand", "pga")).lower() == "masters" else "R3", 2, 0, colors["accent"])
        _page_marks(draw, page, colors)
        for hole in range(18):
            _center(draw, hole + 1, HOLE_X + HOLE_WIDTH // 2 + hole * HOLE_STEP, 1, colors["label"])
        for label, x in (("TODAY", 322), ("TOTAL", 344), ("THRU", 366)):
            _center(draw, label, x, 1, colors["label"])
        shown = players[(page - 1) * 3: page * 3]
        if not shown:
            _center(draw, "LOADING...", 192, 15, colors["accent"])
        for index, player in enumerate(shown):
            _player_row(draw, player, 8 + index * 8, pars, colors)
        return image


def _pane_header(width: int, header: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (width, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    x = max(1, (width - len(header) * 5) // 2)
    draw_hybrid(draw, x + 1, 2, header, HEADER_SHADOW)
    draw_hybrid(draw, x, 1, header, HEADER_TEXT)
    draw.line((0, 7, width - 1, 7), fill=RULE)
    return image, draw


def _match_full(draw: ImageDraw.ImageDraw, golf: dict[str, Any], colors: dict, elapsed: float) -> None:
    """Draw the team totals and three match results of one page."""
    first, second = _teams(golf)
    matches = [match for match in _matches(golf) if isinstance(match, dict)]
    page = _page(elapsed, max(1, (len(matches) + 2) // 3))
    _text(draw, "PRES CUP", 2, 0, colors["accent"])
    total = (f"{_team(first.get('abbr', 'USA'))} {first.get('score', '--')} - "
             f"{_team(second.get('abbr', 'INTL'))} {second.get('score', '--')}")
    _text(draw, total[:24], 42, 0, colors["white"])
    for index, match in enumerate(matches[(page - 1) * 3: page * 3]):
        left, right = _sides(match)
        y = 8 + index * 8 + 1
        result, winner = _result(left, right)
        left_team, right_team = str(left.get("team") or "USA"), str(right.get("team") or "INTL")
        _text(draw, _team(left_team), 2, y, colors["gold"] if winner and left_team == winner else colors["white"])
        _text(draw, _side_name(left, "USA"), 16, y, colors["white"])
        _center(draw, result[:10], 202, y, colors["gold"] if winner else colors["label"])
        _text(draw, _team(right_team), 248, y, colors["gold"] if winner and right_team == winner else colors["white"])
        _text(draw, _side_name(right, "INTL"), 266, y, colors["white"])
    _page_marks(draw, page, colors)


def _player_row(draw: ImageDraw.ImageDraw, player: dict[str, Any], y: int, pars: list[Any], colors: dict) -> None:
    position = str(player["pos"])
    _text(draw, position, 2, y + 1, colors["gold"] if position.replace("T", "") == "1" else colors["white"])
    _text(draw, str(player["name"]).split()[-1][:10], 14, y + 1, colors["white"])
    started = _started(player)
    for hole in range(18):
        _hole(draw, HOLE_X + hole * HOLE_STEP, y, player["holes"][hole] if started else None, pars[hole], colors)
    today = _today(player, pars) if started else None
    _center(draw, _score(today), 322, y + 1, _full_score_color(today, colors))
    _center(draw, _score(player["total"]), 344, y + 1, _full_score_color(player["total"], colors))
    _center(draw, str(player["thru"]).upper()[:3], 366, y + 1, colors["accent"])


def _hole(draw: ImageDraw.ImageDraw, x: int, y: int, score: object, par: object, colors: dict) -> None:
    """Draw one hole score in its scoring shape: diamond eagle, round birdie, open par, square bogey, round double."""
    right = x + HOLE_WIDTH - 1
    if score is None:
        draw.rectangle((x, y, right, y + 6), outline=colors["par"])
        _center(draw, "-", x + HOLE_WIDTH // 2, y + 1, colors["label"])
        return
    value = int(score)
    over = value - int(par)
    if value == 1:
        color = colors["gold"]
    elif over <= -2:
        draw.polygon(((x + 2, y), (right - 2, y), (right, y + 2), (right, y + 4), (right - 2, y + 6), (x + 2, y + 6),
                      (x, y + 4), (x, y + 2)), fill=colors["eagle"])
        color = colors["black"]
    elif over == -1:
        draw.ellipse((x, y, right, y + 6), fill=colors["birdie"])
        color = colors["black"]
    elif over == 0:
        draw.rectangle((x, y, right, y + 6), outline=colors["par"])
        color = colors["white"]
    elif over == 1:
        draw.rectangle((x, y, right, y + 6), fill=colors["bogey"])
        color = colors["white"]
    else:
        draw.ellipse((x, y, right, y + 6), fill=colors["double"])
        color = colors["white"]
    _center(draw, value, x + HOLE_WIDTH // 2, y + 1, color)


def _page_marks(draw: ImageDraw.ImageDraw, page: int, colors: dict) -> None:
    """Mark the shown page in the column of five page marks at the right edge."""
    for index in range(5):
        y = 1 + index * 6
        draw.rectangle((381, y, 382, y + 1), fill=colors["active"] if index + 1 == page else colors["idle"])


def _page(elapsed: float, pages: int) -> int:
    return int(max(0.0, elapsed) // PAGE_SECONDS) % pages + 1


def _text(draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
    GOLF_FONT.draw(draw, x, y, clean_text(text), color)


def _center(draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
    _text(draw, text, int(x - max(0, len(str(text)) * 4 - 1) // 2), y, color)


# Data

def _golf(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("golf") or item.get("masters") or {}
    return value if isinstance(value, dict) else {}


def _players(golf: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the shown players. Withdrawn and disqualified players are left out. Unranked players get ranks."""
    players = []
    for raw in golf.get("players", []) if isinstance(golf.get("players"), list) else []:
        if not isinstance(raw, dict) or str(raw.get("pos", "")).upper() in {"WD", "DQ"}:
            continue
        name = clean_text(raw.get("name", "UNKNOWN"))
        parts = name.split()
        holes = raw.get("holes", []) if isinstance(raw.get("holes"), list) else []
        players.append({"pos": str(raw.get("pos", "-")).upper() or "-",
                        "name": (f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else name).upper()[:11],
                        "total": _integer(raw.get("total")), "today": _optional_integer(raw.get("today")),
                        "thru": raw.get("thru", 0), "holes": holes[:18] + [None] * max(0, 18 - len(holes))})
    if players and all(player["pos"] in {"", "-"} for player in players):
        players.sort(key=lambda player: player["total"])
        totals = [player["total"] for player in players]
        for rank, player in enumerate(players, start=1):
            player["pos"] = f"T{rank}" if totals.count(player["total"]) > 1 else str(rank)
    return players


def _teams(golf: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    teams = golf.get("teams", []) if isinstance(golf.get("teams"), list) else []
    return tuple(teams[index] if len(teams) > index and isinstance(teams[index], dict) else {} for index in (0, 1))


def _matches(golf: dict[str, Any]) -> list[Any]:
    return golf.get("matches", []) if isinstance(golf.get("matches"), list) else []


def _sides(match: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sides = match.get("sides", []) if isinstance(match.get("sides"), list) else []
    return tuple(sides[index] if len(sides) > index and isinstance(sides[index], dict) else {} for index in (0, 1))


def _side_name(side: dict[str, Any], team: str) -> str:
    if side.get("player"):
        parts = str(side["player"]).split()
        return f"{parts[0][0]}. {parts[-1]}".upper() if len(parts) > 1 else str(side["player"]).upper()
    return _team(side.get("team", team))


def _team(value: object) -> str:
    label = clean_text(value).strip().upper()
    return TEAM_NAMES.get(label, label[:3])


def _result(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str]:
    """Return the match result text and the winning team. An undecided match has no winner."""
    left_score, right_score = str(left.get("score") or "").strip(), str(right.get("score") or "").strip()
    score = left_score or right_score
    key = score.casefold().replace(" ", "")
    if key in {"as", "allsquare", "halved"}:
        return ("HALVED" if key == "halved" else "AS"), ""
    if not score:
        return "PRE", ""
    winner = str((left.get("team") if left_score else right.get("team")) or "")
    return f"{_team(winner)} {score}".upper(), winner


def _today(player: dict[str, Any], pars: list[Any]) -> int | None:
    """Return the round score, or add up the finished holes against par."""
    if player["today"] is not None:
        return int(player["today"])
    scores = [(score, pars[index]) for index, score in enumerate(player["holes"]) if score is not None and index < len(pars)]
    return sum(int(score) - int(par) for score, par in scores) if scores else None


def _started(player: dict[str, Any]) -> bool:
    try:
        return int(player["thru"] or 0) > 0 or any(score is not None for score in player["holes"])
    except (TypeError, ValueError):
        return str(player["thru"]).upper() == "F" or any(score is not None for score in player["holes"])


def _integer(value: object) -> int:
    try:
        text = str(value).strip().upper()
        return 0 if text in {"", "--", "E", "EVEN"} else int(float(text))
    except (TypeError, ValueError):
        return 0


def _optional_integer(value: object) -> int | None:
    return None if value is None or str(value).strip().upper() in {"", "--"} else _integer(value)


def _score(value: int | None) -> str:
    return "--" if value is None else "E" if value == 0 else f"+{value}" if value > 0 else str(value)


def _pane_score_color(value: object) -> tuple[int, int, int]:
    try:
        return (100, 210, 100) if int(value) < 0 else (220, 80, 80) if int(value) > 0 else (255, 255, 255)
    except (TypeError, ValueError):
        return (255, 255, 255)


def _full_score_color(value: object, colors: dict):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return colors["label"]
    return colors["birdie"] if number < 0 else colors["bogey"] if number > 0 else colors["white"]

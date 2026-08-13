"""Render golf views with explicit pair rotation state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.features.utility.primitives import PANEL_H, PANEL_W, hybrid_text, normal_text, tiny_text
from ticker_core.rendering import ContentScene, FontSet, RenderedContent


@dataclass(frozen=True, slots=True)
class GolfAnimationState:
    """Track the visible full-screen player pair."""

    pair: int = 0
    changed_at: float | None = None


class GolfRenderer:
    """Render compact and full golf scoreboards."""

    _font = {
        "A": [2, 5, 7, 5, 5], "B": [6, 5, 7, 5, 6], "C": [7, 4, 4, 4, 7], "D": [6, 5, 5, 5, 6], "E": [7, 4, 7, 4, 7], "F": [7, 4, 7, 4, 4], "G": [7, 4, 5, 5, 7], "H": [5, 5, 7, 5, 5], "I": [7, 2, 2, 2, 7], "J": [1, 1, 1, 5, 2], "K": [5, 6, 4, 6, 5], "L": [4, 4, 4, 4, 7], "M": [5, 7, 7, 5, 5], "N": [5, 7, 5, 5, 5], "O": [7, 5, 5, 5, 7], "P": [7, 5, 7, 4, 4], "Q": [7, 5, 5, 7, 1], "R": [7, 5, 6, 5, 5], "S": [7, 4, 7, 1, 7], "T": [7, 2, 2, 2, 2], "U": [5, 5, 5, 5, 7], "V": [5, 5, 5, 2, 2], "W": [5, 5, 7, 7, 5], "X": [5, 5, 2, 5, 5], "Y": [5, 5, 2, 2, 2], "Z": [7, 1, 2, 4, 7], "0": [7, 5, 5, 5, 7], "1": [2, 6, 2, 2, 7], "2": [7, 1, 7, 4, 7], "3": [7, 1, 7, 1, 7], "4": [5, 5, 7, 1, 1], "5": [7, 4, 7, 1, 7], "6": [7, 4, 7, 5, 7], "7": [7, 1, 1, 1, 1], "8": [7, 5, 7, 5, 7], "9": [7, 5, 7, 1, 7], "-": [0, 0, 7, 0, 0], "+": [0, 2, 7, 2, 0], ".": [0, 0, 0, 0, 2], " ": [0, 0, 0, 0, 0],
    }

    def __init__(self, fonts: FontSet) -> None:
        self._fonts = fonts

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render the mode-selected golf view."""
        if scene.item.get("sports_presentation") == "pinned":
            image, _ = self.full(context, scene.item, GolfAnimationState())
            return RenderedContent(image, static=True)
        return RenderedContent(self.scroll(scene.item), static=False)

    def scroll(self, item: object) -> Image.Image:
        """Render the compact top-three score card."""
        game = item if isinstance(item, dict) else {}
        payload = self._payload(game)
        event = str(payload.get("event_name") or game.get("away_abbr") or "PGA TOUR").upper()
        round_label = str(payload.get("round") or game.get("status") or "").upper()
        match = re.search(r"\d+", round_label)
        header = f"{event} R{match.group() if match else '-'}"
        width = max(128, len(header) * 5 + 4)
        image = Image.new("RGBA", (width, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        x = max(1, (width - len(header) * 5) // 2)
        hybrid_text(draw, x + 1, 2, header, (8, 8, 8, 180), self._fonts.tiny)
        hybrid_text(draw, x, 1, header, (255, 240, 150, 255), self._fonts.tiny)
        draw.line((0, 7, width - 1, 7), fill=(55, 76, 130))
        tiny_text(draw, 72, 8, "TODAY", (80, 95, 130), self._fonts.tiny)
        tiny_text(draw, 100, 8, "TOTAL", (80, 95, 130), self._fonts.tiny)
        players = self._players(payload, compact=True)[:3]
        pars = payload.get("pars", []) if isinstance(payload.get("pars"), list) else []
        if not players:
            tiny_text(draw, 18, 18, "LOADING", (150, 150, 150), self._fonts.tiny)
            return image
        for index, player in enumerate(players):
            y = (14, 20, 26)[index]
            pos = str(player["pos"])[:3]
            raw_name = str(player["name"])
            parts = raw_name.split()
            name = (f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else raw_name).upper()[:10]
            today = player["today"] if self._started(player) else None
            if today is None and self._started(player) and pars:
                scores = [(score, pars[i]) for i, score in enumerate(player["holes"][:18]) if score is not None and i < len(pars)]
                if scores:
                    today = sum(int(score) - int(par) for score, par in scores)
            pos_color = (255, 215, 0) if pos.replace("T", "") == "1" else (220, 80, 80) if pos == "CUT" else (200, 200, 200)
            today_text = self._score(today)
            total_text = self._score(player["total"])
            tiny_text(draw, 1, y, pos, pos_color, self._fonts.tiny)
            tiny_text(draw, 18, y, name, "white", self._fonts.tiny)
            tiny_text(draw, 84 - len(today_text) * 5 // 2, y, today_text, self._score_color(today), self._fonts.tiny)
            tiny_text(draw, 112 - len(total_text) * 5 // 2, y, total_text, self._score_color(player["total"]), self._fonts.tiny)
        return image

    def full(self, context: RenderContext, item: object, state: GolfAnimationState) -> tuple[Image.Image, GolfAnimationState]:
        """Render the complete paired-player golf screen."""
        game = item if isinstance(item, dict) else {}
        payload = self._payload(game)
        colors = self._colors(game)
        image = Image.new("RGBA", (PANEL_W, PANEL_H), colors["bg"])
        draw = ImageDraw.Draw(image)
        event = str(payload.get("event_name") or "PGA TOUR").upper()
        year = str(payload.get("year") or game.get("away_score") or context.now.year)
        pars = payload.get("pars", []) if isinstance(payload.get("pars"), list) else []
        pars = (pars + [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4])[:18]
        players = self._players(payload, compact=False)[:20]
        pairs = [(players[i], players[i + 1] if i + 1 < len(players) else None) for i in range(0, len(players), 2)]
        pair = state.pair % len(pairs) if pairs else 0
        changed = context.now.timestamp() if state.changed_at is None else state.changed_at
        if pairs:
            selected = pairs[pair]
            interval = 2.0 if selected[0]["pos"] == "CUT" or (selected[1] and selected[1]["pos"] == "CUT") else 4.0
            if context.now.timestamp() - changed > interval:
                pair = (pair + 1) % len(pairs)
                changed = context.now.timestamp()
        next_state = GolfAnimationState(pair, changed)
        brand = payload.get("brand") if isinstance(payload.get("brand"), list) else []
        brand = brand if len(brand) >= 2 else [event[:7], ""]
        draw.line((30, 0, 30, 31), fill=colors["gold"])
        self._center(draw, brand[0], 15, 3, colors["gold"])
        self._center(draw, brand[1], 15, 11, colors["gold"])
        self._center(draw, year, 15, 20, colors["gold"])
        if not pairs:
            self._center(draw, event[:16], 207, 10, colors["white"])
            self._center(draw, "LOADING...", 207, 20, colors["gold"])
            return image, next_state
        for value in range(1, 10):
            self._center(draw, value, 95 + (value - 1) * 10 + 3, 2, colors["label"])
        self._center(draw, "FRONT", 194, 2, colors["label"])
        for value in range(10, 19):
            self._center(draw, value, 208 + (value - 10) * 11 + 3, 2, colors["label"])
        self._center(draw, "BACK", 314, 2, colors["label"])
        self._center(draw, "TODAY", 342, 2, colors["label"])
        self._center(draw, "TOTAL", 368, 2, colors["label"])
        first, second = pairs[pair]
        self._player(draw, first, 9, pars, colors)
        if second:
            draw.line((34, 19, PANEL_W - 4, 19), fill=colors["par"])
            self._player(draw, second, 22, pars, colors)
        dots = len(pairs)
        step = 0 if dots <= 1 else max(2, min(4, (PANEL_W - 6) // (dots - 1)))
        start = PANEL_W - (2 if dots == 1 else (dots - 1) * step + 2) - 2
        for index in range(dots):
            draw.rectangle((start + index * step, 30, start + index * step + 1, 31), fill=colors["active"] if index == pair else colors["idle"])
        return image, next_state

    def _player(self, draw: ImageDraw.ImageDraw, player: dict[str, Any], y: int, pars: list[Any], colors: dict[str, tuple[int, int, int, int]]) -> None:
        pos = str(player["pos"])
        if pos.replace("T", "") == "1":
            draw.rectangle((30, y + 1, 31, y + 5), fill=colors["gold"])
        self._text(draw, pos, 34, y + 1, colors["bogey"] if pos == "CUT" else colors["gold"] if pos.replace("T", "") == "1" else colors["white"])
        self._text(draw, player["name"], 47, y + 1, colors["white"])
        started = self._started(player)
        front = 0
        for index in range(9):
            score = player["holes"][index] if started else None
            self._box(draw, 95 + index * 10, y, score, pars[index], colors)
            if score is not None:
                front += int(score) - int(pars[index])
        self._center(draw, self._score(front), 194, y + 1, colors["white"])
        back = 0
        for index in range(9):
            score = player["holes"][9 + index] if started else None
            self._box(draw, 208 + index * 11, y, score, pars[9 + index], colors)
            if score is not None:
                back += int(score) - int(pars[9 + index])
        self._center(draw, self._score(back), 314, y + 1, colors["white"])
        self._center(draw, self._score(player["today"]) if started and player["today"] is not None else "-", 342, y + 1, colors["white"] if started and player["today"] is not None else colors["label"])
        total = player["total"]
        self._center(draw, self._score(total), 368, y + 1, colors["birdie"] if total < 0 else colors["bogey"] if total > 0 else colors["white"])

    def _box(self, draw: ImageDraw.ImageDraw, x: int, y: int, score: object, par: object, colors: dict[str, tuple[int, int, int, int]]) -> None:
        if score is None:
            draw.rectangle((x, y, x + 6, y + 6), outline=colors["par"])
            self._center(draw, "-", x + 3, y + 1, colors["label"])
            return
        value = int(score)
        diff = value - int(par)
        if diff <= -2:
            draw.ellipse((x, y, x + 6, y + 6), fill=colors["eagle"])
            self._center(draw, value, x + 3, y + 1, colors["black"])
        elif diff == -1:
            draw.ellipse((x, y, x + 6, y + 6), fill=colors["birdie"])
            self._center(draw, value, x + 3, y + 1, colors["black"])
        elif diff == 0:
            draw.rectangle((x, y, x + 6, y + 6), outline=colors["par"])
            self._center(draw, value, x + 3, y + 1, colors["white"])
        else:
            draw.rectangle((x, y, x + 6, y + 6), fill=colors["bogey"] if diff == 1 else colors["double"])
            self._center(draw, value, x + 3, y + 1, colors["white"])

    def _players(self, payload: dict[str, Any], compact: bool) -> list[dict[str, Any]]:
        raw = payload.get("players", []) if isinstance(payload.get("players"), list) else []
        players: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or str(item.get("pos", "")).upper() in {"WD", "DQ"}:
                continue
            raw_name = normal_text(item.get("name", "UNKNOWN"))
            parts = raw_name.split()
            name = (f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else raw_name).upper()[:11]
            players.append({"pos": str(item.get("pos", "-")).upper() or "-", "name": name, "total": self._integer(item.get("total")), "today": self._optional_int(item.get("today")), "thru": item.get("thru", 0), "holes": (item.get("holes", []) if isinstance(item.get("holes"), list) else [])[:18] + [None] * max(0, 18 - len(item.get("holes", []) if isinstance(item.get("holes"), list) else []))})
        if players and all(player["pos"] in {"", "-"} for player in players):
            players.sort(key=lambda player: player["total"])
            totals = [player["total"] for player in players]
            for index, player in enumerate(players):
                rank = index + 1
                player["pos"] = f"T{rank}" if totals.count(player["total"]) > 1 else str(rank)
        return players

    @staticmethod
    def _payload(game: dict[str, Any]) -> dict[str, Any]:
        value = game.get("golf") or game.get("masters") or {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _integer(value: object) -> int:
        try:
            text = str(value).strip().upper()
            return 0 if text in {"", "--", "E", "EVEN"} else int(float(text))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _optional_int(cls, value: object) -> int | None:
        return None if value is None or str(value).strip().upper() in {"", "--"} else cls._integer(value)

    @staticmethod
    def _started(player: dict[str, Any]) -> bool:
        try:
            return int(player["thru"] or 0) > 0 or any(score is not None for score in player["holes"])
        except (TypeError, ValueError):
            return str(player["thru"]).upper() == "F" or any(score is not None for score in player["holes"])

    @staticmethod
    def _score(value: int | None) -> str:
        return "--" if value is None else "E" if value == 0 else f"+{value}" if value > 0 else str(value)

    @staticmethod
    def _score_color(value: object) -> tuple[int, int, int]:
        try:
            return (100, 210, 100) if int(value) < 0 else (220, 80, 80) if int(value) > 0 else (255, 255, 255)
        except (TypeError, ValueError):
            return (255, 255, 255)

    @staticmethod
    def _colors(game: dict[str, Any]) -> dict[str, tuple[int, int, int, int]]:
        def parse(value: object, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            try:
                text = str(value).lstrip("#")
                return int(text[:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255
            except (TypeError, ValueError):
                return fallback
        gold = parse(game.get("away_color"), (200, 168, 75, 255))
        return {"bg": parse(game.get("away_alt_color"), (0, 76, 53, 255)), "gold": gold, "eagle": (250, 204, 21, 255), "birdie": (34, 197, 94, 255), "bogey": (239, 68, 68, 255), "double": (153, 27, 27, 255), "par": (245, 220, 130, 255), "white": (255, 255, 255, 255), "black": (0, 0, 0, 255), "label": (235, 245, 225, 255), "active": gold, "idle": (132, 132, 132, 255)}

    def _text(self, draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
        cursor = x
        for character in str(text).upper():
            pattern = self._font.get(character)
            if pattern:
                for row, value in enumerate(pattern):
                    for column in range(3):
                        if (value >> (2 - column)) & 1:
                            draw.point((cursor + column, y + row), fill=color)
            cursor += 4

    def _center(self, draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
        self._text(draw, text, int(x - max(0, len(str(text)) * 4 - 1) // 2), y, color)

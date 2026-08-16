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
    """Track the visible golf page."""

    pair: int = 0
    page: int = 1
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
            image, _ = self.full(context, scene.item, GolfAnimationState(), elapsed=scene.elapsed)
            return RenderedContent(image)
        return RenderedContent(self.scroll(scene.item))

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
        total_x = width - 27
        total_center = width - 15
        today_x = width - 55
        today_center = width - 43
        tiny_text(draw, today_x, 8, "TODAY", (80, 95, 130), self._fonts.tiny)
        tiny_text(draw, total_x, 8, "TOTAL", (80, 95, 130), self._fonts.tiny)
        players = self._players(payload, compact=True)[:3]
        pars = payload.get("pars", []) if isinstance(payload.get("pars"), list) else []
        if not players:
            tiny_text(draw, 18, 18, "LOADING", (150, 150, 150), self._fonts.tiny)
            return image
        max_name_len = max(8, (today_x - 20) // 5)
        for index, player in enumerate(players):
            y = (14, 20, 26)[index]
            pos = str(player["pos"])[:3]
            raw_name = str(player["name"])
            parts = raw_name.split()
            name = (f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else raw_name).upper()[:max_name_len]
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
            tiny_text(draw, today_center - len(today_text) * 5 // 2, y, today_text, self._score_color(today), self._fonts.tiny)
            tiny_text(draw, total_center - len(total_text) * 5 // 2, y, total_text, self._score_color(player["total"]), self._fonts.tiny)
        return image

    def full(
        self,
        context: RenderContext,
        item: object,
        state: GolfAnimationState,
        *,
        elapsed: float | None = None,
    ) -> tuple[Image.Image, GolfAnimationState]:
        """Render the full 18-hole golf screen."""
        game = item if isinstance(item, dict) else {}
        payload = self._payload(game)
        colors = self._colors(game)
        image = Image.new("RGBA", (PANEL_W, PANEL_H), colors["bg"])
        draw = ImageDraw.Draw(image)
        pars = payload.get("pars", []) if isinstance(payload.get("pars"), list) else []
        pars = (pars + [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4])[:18]
        all_players = self._players(payload, compact=False)
        page_count = max(1, min(5, (len(all_players) + 2) // 3))
        page = min(max(1, state.page), page_count)
        if elapsed is None:
            changed = context.now.timestamp() if state.changed_at is None else state.changed_at
            if context.now.timestamp() - changed > 4.0:
                page = page % page_count + 1
                changed = context.now.timestamp()
        else:
            page = int(max(0.0, elapsed) // 4.0) % page_count + 1
            changed = None
        next_state = GolfAnimationState(state.pair, page, changed)
        header = "MASTERS R3" if str(payload.get("brand", "pga")).lower() == "masters" else "R3"
        self._text(draw, header, 2, 0, colors["accent"])
        self._page_indicator(draw, page, colors)
        hole_x = 58
        hole_step = 14
        hole_width = 9
        for index in range(18):
            self._center(draw, index + 1, hole_x + hole_width // 2 + index * hole_step, 1, colors["label"])
        self._center(draw, "TODAY", 322, 1, colors["label"])
        self._center(draw, "TOTAL", 344, 1, colors["label"])
        self._center(draw, "THRU", 366, 1, colors["label"])
        players = all_players[(page - 1) * 3 : page * 3]
        if not players:
            self._center(draw, "LOADING...", 192, 15, colors["accent"])
            return image, next_state
        for index, player in enumerate(players):
            self._player(draw, player, 8 + index * 8, pars, colors, hole_x, hole_step, hole_width)
        return image, next_state

    def _page_indicator(self, draw: ImageDraw.ImageDraw, page: int, colors: dict[str, tuple[int, int, int, int]]) -> None:
        """Show the active page in the vertical five-page indicator."""

        for index in range(5):
            color = colors["active"] if index + 1 == page else colors["idle"]
            y = 1 + index * 6
            draw.rectangle((381, y, 382, y + 1), fill=color)

    def _player(
        self,
        draw: ImageDraw.ImageDraw,
        player: dict[str, Any],
        y: int,
        pars: list[Any],
        colors: dict[str, tuple[int, int, int, int]],
        hole_x: int,
        hole_step: int,
        hole_width: int,
    ) -> None:
        pos = str(player["pos"])
        name = str(player["name"]).split()[-1][:10]
        self._text(draw, pos, 2, y + 1, colors["gold"] if pos.replace("T", "") == "1" else colors["white"])
        self._text(draw, name, 14, y + 1, colors["white"])
        started = self._started(player)
        for index in range(18):
            score = player["holes"][index] if started else None
            self._box(draw, hole_x + index * hole_step, y, score, pars[index], colors, hole_width)
        today = self._today(player, pars) if started else None
        total = player["total"]
        self._center(draw, self._score(today), 322, y + 1, self._full_score_color(today, colors))
        self._center(draw, self._score(total), 344, y + 1, self._full_score_color(total, colors))
        self._center(draw, str(player["thru"]).upper()[:3], 366, y + 1, colors["accent"])

    @staticmethod
    def _today(player: dict[str, Any], pars: list[Any]) -> int | None:
        """Return the supplied round score or derive it from completed holes."""

        if player["today"] is not None:
            return int(player["today"])
        scores = [(score, pars[index]) for index, score in enumerate(player["holes"]) if score is not None and index < len(pars)]
        return sum(int(score) - int(par) for score, par in scores) if scores else None

    def _box(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        score: object,
        par: object,
        colors: dict[str, tuple[int, int, int, int]],
        width: int,
    ) -> None:
        if score is None:
            draw.rectangle((x, y, x + width - 1, y + 6), outline=colors["par"])
            self._center(draw, "-", x + width // 2, y + 1, colors["label"])
            return
        value = int(score)
        diff = value - int(par)
        if value == 1:
            color = colors["gold"]
        elif diff <= -2:
            right = x + width - 1
            draw.polygon(((x + 2, y), (right - 2, y), (right, y + 2), (right, y + 4), (right - 2, y + 6), (x + 2, y + 6), (x, y + 4), (x, y + 2)), fill=colors["eagle"])
            color = colors["black"]
        elif diff == -1:
            draw.ellipse((x, y, x + width - 1, y + 6), fill=colors["birdie"])
            color = colors["black"]
        elif diff == 0:
            draw.rectangle((x, y, x + width - 1, y + 6), outline=colors["par"])
            color = colors["white"]
        elif diff == 1:
            draw.rectangle((x, y, x + width - 1, y + 6), fill=colors["bogey"])
            color = colors["white"]
        else:
            draw.ellipse((x, y, x + width - 1, y + 6), fill=colors["double"])
            color = colors["white"]
        self._center(draw, value, x + width // 2, y + 1, color)

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
    def _full_score_color(value: object, colors: dict[str, tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        """Choose a full-panel score color from the active golf palette."""

        try:
            integer = int(value)
        except (TypeError, ValueError):
            return colors["label"]
        return colors["birdie"] if integer < 0 else colors["bogey"] if integer > 0 else colors["white"]

    @staticmethod
    def _colors(game: dict[str, Any]) -> dict[str, tuple[int, int, int, int]]:
        masters = str(GolfRenderer._payload(game).get("brand", "pga")).lower() == "masters"
        if masters:
            return {
                "bg": (0, 14, 8, 255),
                "gold": (231, 199, 92, 255),
                "eagle": (231, 199, 92, 255),
                "birdie": (164, 225, 155, 255),
                "bogey": (241, 139, 119, 255),
                "double": (170, 67, 65, 255),
                "par": (145, 169, 145, 255),
                "white": (244, 248, 231, 255),
                "black": (0, 39, 27, 255),
                "label": (145, 169, 145, 255),
                "accent": (231, 199, 92, 255),
                "active": (231, 199, 92, 255),
                "idle": (24, 50, 33, 255),
            }
        return {
            "bg": (0, 0, 0, 255),
            "gold": (235, 196, 83, 255),
            "eagle": (235, 196, 83, 255),
            "birdie": (68, 211, 128, 255),
            "bogey": (240, 103, 103, 255),
            "double": (157, 43, 67, 255),
            "par": (112, 124, 136, 255),
            "white": (241, 246, 250, 255),
            "black": (0, 0, 0, 255),
            "label": (112, 124, 136, 255),
            "accent": (91, 171, 221, 255),
            "active": (91, 171, 221, 255),
            "idle": (25, 30, 35, 255),
        }

    def _text(self, draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
        cursor = x
        for character in normal_text(text).upper():
            pattern = self._font.get(character)
            if pattern:
                for row, value in enumerate(pattern):
                    for column in range(3):
                        if (value >> (2 - column)) & 1:
                            draw.point((cursor + column, y + row), fill=color)
            cursor += 4

    def _center(self, draw: ImageDraw.ImageDraw, text: object, x: int, y: int, color: object) -> None:
        self._text(draw, text, int(x - max(0, len(str(text)) * 4 - 1) // 2), y, color)

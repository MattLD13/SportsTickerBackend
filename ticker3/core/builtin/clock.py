"""The clock. The device draws the time from its own clock, so the record holds only the zone and the format."""
from __future__ import annotations

from typing import Any

MANIFEST = {
    "feature": "clock",
    "title": "Clock",
    "version": "1",
    "settings": {"fields": {
        "timezone": {"type": "string", "default": "America/New_York", "pattern": r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}|UTC"},
        "format": {"type": "enum", "values": ["12h", "24h"], "default": "12h"},
        "color": {"type": "string", "default": "#ffffff", "pattern": "#[0-9a-f]{6}", "role": "view"},
    }},
    "templates": [{
        "id": "clock.face",
        "version": 1,
        "panels": {
            "w384h32": {"box": [384, 32], "flow": "page", "dwell": 10, "parts": [
                {"part": "clock", "at": [192, 2], "font": "clock", "align": "center", "color": "{app.color}",
                 "tz": "{tz}", "format": "{format}"},
            ]},
            "w64h32": {"box": [64, 32], "flow": "page", "dwell": 10, "parts": [
                {"part": "clock", "at": [32, 9], "font": "big", "align": "center", "color": "{app.color}",
                 "tz": "{tz}", "format": "{format}"},
            ]},
        },
    }],
}


def records(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": "clock", "template": "clock.face", "values": {"tz": config["timezone"], "format": config["format"]}}]

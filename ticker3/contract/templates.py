"""Validate screen templates and evaluate their value rules.

A template has one block for each panel size:

    {"id": "sports.card", "version": 1, "panels": {
        "w64h32": {"box": [64, 32], "flow": "page", "dwell": 8, "parts": [...]}}}

Each part draws one thing. The player owns the drawing. The template owns only
the position, the font, the color, and the value.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from . import ContractError
from .records import TEMPLATE_ID
from .wire import canonical

PANEL = re.compile(r"^w([1-9][0-9]{0,3})h([1-9][0-9]{0,2})$")
PANELS = ("w384h32", "w64h32")
FLOWS = ("scroll", "page")
FONTS = ("micro", "tiny", "small", "medium", "big", "huge", "clock")
ICONS = ("sun", "moon", "partly", "cloud", "rain", "snow", "storm", "fog", "wind", "football", "flag")
ALIGN = ("left", "center", "right")
COLOR = re.compile(r"^#[0-9a-f]{6}$")
PLACEHOLDER = re.compile(r"\{([a-z0-9_.]+)\}")
RULE = re.compile(r"""^(!?)([a-z0-9_.]+)(?:\s*(==|!=)\s*([A-Za-z0-9_.:+-]+|'[^']*'|"[^"]*"))?$""")

# Each part type lists its required and optional fields after "part" and "at".
PARTS: dict[str, tuple[set[str], set[str]]] = {
    "text": ({"font", "value"}, {"color", "align", "max_width"}),
    "rect": ({"size"}, {"color"}),
    "logo": ({"size", "value"}, set()),
    "icon": ({"value"}, {"color"}),
    "bases": ({"value"}, {"size", "color"}),
    "dots": ({"value"}, {"spacing"}),
    "clock": ({"font", "tz", "format"}, {"color", "align"}),
    "time": ({"font", "value", "tz", "format"}, {"color", "align"}),
}
# A time part formats an epoch value in the zone of the ticker.
TIME_FORMATS = ("time", "weekday_time", "date", "weekday")


def validate_template(template: Any) -> dict[str, Any]:
    """Return the template when each panel block and part is valid."""
    if not isinstance(template, dict) or set(template) != {"id", "version", "panels"}:
        raise ContractError("template must have exactly id, version, and panels")
    identifier = template["id"]
    if not isinstance(identifier, str) or not TEMPLATE_ID.match(identifier):
        raise ContractError(f"template id {identifier!r} is invalid")
    version = template["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ContractError(f"template {identifier} version must be a positive integer")
    panels = template["panels"]
    if not isinstance(panels, dict) or not panels:
        raise ContractError(f"template {identifier} needs at least one panel block")
    for panel, block in panels.items():
        _validate_block(identifier, panel, block)
    return template


def bundle(templates: dict[str, dict[str, Any]], panel: str) -> tuple[str, dict[str, Any]]:
    """Return the bundle hash and the blocks of each template for one panel size."""
    blocks = {
        identifier: {"version": template["version"], **template["panels"][panel]}
        for identifier, template in sorted(templates.items()) if panel in template["panels"]
    }
    return hashlib.sha256(canonical(blocks).encode()).hexdigest()[:16], blocks


def text_of(value: Any) -> str | None:
    """Return the display text of one scalar value. None means the value is missing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def fill(pattern: str, values: dict[str, Any]) -> str | None:
    """Replace each {key} with its value. Return None if any key is missing."""
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        text = text_of(values.get(match.group(1)))
        if text is None:
            missing = True
            return ""
        return text

    result = PLACEHOLDER.sub(replace, pattern)
    return None if missing else result


def shown(rule: str | None, values: dict[str, Any]) -> bool:
    """Evaluate one show rule: key, !key, key == literal, or key != literal."""
    if rule is None:
        return True
    match = RULE.match(rule.strip())
    if match is None:
        raise ContractError(f"invalid show rule {rule!r}")
    negate, key, operator, literal = match.groups()
    text = text_of(values.get(key))
    if operator is None:
        present = text not in (None, "", "false", "0")
        return present != bool(negate)
    if negate:
        raise ContractError(f"show rule {rule!r} cannot combine ! with a comparison")
    equal = text == literal.strip("'\"")
    return equal if operator == "==" else not equal


def _validate_block(identifier: str, panel: Any, block: Any) -> None:
    size = PANEL.match(str(panel))
    if size is None:
        raise ContractError(f"template {identifier} has an invalid panel name {panel!r}")
    width, height = int(size.group(1)), int(size.group(2))
    if not isinstance(block, dict) or not {"box", "flow", "parts"} <= set(block) <= {"box", "flow", "dwell", "parts"}:
        raise ContractError(f"template {identifier} {panel} needs box, flow, and parts")
    box = block["box"]
    if not _pair(box) or not 1 <= box[0] <= width or box[1] != height:
        raise ContractError(f"template {identifier} {panel} box must fit the panel width and match its height")
    if block["flow"] not in FLOWS:
        raise ContractError(f"template {identifier} {panel} flow must be scroll or page")
    dwell = block.get("dwell", 8)
    if isinstance(dwell, bool) or not isinstance(dwell, int) or not 2 <= dwell <= 120:
        raise ContractError(f"template {identifier} {panel} dwell must be 2 to 120 seconds")
    if not isinstance(block["parts"], list) or not block["parts"]:
        raise ContractError(f"template {identifier} {panel} needs parts")
    for index, part in enumerate(block["parts"]):
        _validate_part(f"template {identifier} {panel} part {index}", part, box)


def _validate_part(where: str, part: Any, box: list[int]) -> None:
    if not isinstance(part, dict) or part.get("part") not in PARTS:
        raise ContractError(f"{where} has an unknown part type")
    required, optional = PARTS[part["part"]]
    fields = set(part) - {"part", "at", "show_when"}
    if not required <= fields or not fields <= required | optional:
        raise ContractError(f"{where} needs {sorted(required)} and allows {sorted(optional)}")
    at = part.get("at")
    if not _pair(at) or not (0 <= at[0] < box[0] and 0 <= at[1] < box[1]):
        raise ContractError(f"{where} position must be inside the box")
    if "show_when" in part:
        if not isinstance(part["show_when"], str):
            raise ContractError(f"{where} show_when must be text")
        shown(part["show_when"], {})
    for name in ("value", "tz", "format"):
        if name in part and (not isinstance(part[name], str) or "{" in PLACEHOLDER.sub("", part[name])):
            raise ContractError(f"{where} {name} must be text with {{key}} placeholders")
    if part["part"] == "time" and part["format"] not in TIME_FORMATS:
        raise ContractError(f"{where} format must be one of {', '.join(TIME_FORMATS)}")
    if "font" in part and part["font"] not in FONTS:
        raise ContractError(f"{where} font must be one of {', '.join(FONTS)}")
    if "align" in part and part["align"] not in ALIGN:
        raise ContractError(f"{where} align must be left, center, or right")
    if "color" in part and not (isinstance(part["color"], str) and (COLOR.match(part["color"]) or PLACEHOLDER.fullmatch(part["color"]))):
        raise ContractError(f"{where} color must be #rrggbb or one {{key}}")
    if "size" in part:
        size = part["size"]
        valid = _pair(size) if part["part"] == "rect" else isinstance(size, int) and not isinstance(size, bool) and 1 <= size <= 32
        if not valid:
            raise ContractError(f"{where} has an invalid size")
    for name in ("max_width", "spacing"):
        if name in part and (isinstance(part[name], bool) or not isinstance(part[name], int) or not 1 <= part[name] <= 384):
            raise ContractError(f"{where} {name} must be 1 to 384")


def _pair(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 1024 for item in value))

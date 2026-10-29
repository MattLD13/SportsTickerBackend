"""Render the production offline panel at representative connection ages."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ticker_core.ui.frame import RenderContext
from ticker_core.features.utility import UtilityRenderer
from ticker_core.ui import load_default_font_set

STEPS = (("1m", 65), ("12m", 720), ("3h", 10800), ("2d", 172800))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("previews/offline"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    renderer = UtilityRenderer(load_default_font_set())
    context = RenderContext(now=datetime.now())
    for label, seconds in STEPS:
        renderer.offline(context, seconds).convert("RGB").save(args.out_dir / ("offline_" + label + ".png"))


if __name__ == "__main__":
    main()

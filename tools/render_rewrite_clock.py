"""Render a rewrite clock frame as a PNG file."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ticker_core import RenderContext
from ticker_core.bootstrap import create_default_scene_registry
from ticker_core.features.clock import ClockScene


def parse_datetime(value: str) -> datetime:
    """Parse an ISO datetime value."""
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use an ISO datetime value.") from error


def main() -> None:
    """Render the requested clock frame."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--datetime",
        type=parse_datetime,
        default=datetime.now(),
        help="Use this ISO datetime. The default is the local current time.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("previews/rewrite_clock.png"),
        help="Save the PNG at this path.",
    )
    arguments = parser.parse_args()

    image = create_default_scene_registry().render(
        RenderContext(arguments.datetime), ClockScene()
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(arguments.output)
    print(f"Saved {arguments.output}")


if __name__ == "__main__":
    main()

"""Run the rewrite Pi ticker application."""

from __future__ import annotations

import os

from .composition import create_application


def main() -> None:
    """Start the selected ticker sink until a process interrupt arrives."""
    os.environ["TICKER_MATRIX_REFRESH_HZ"] = "120"
    application = create_application()
    try:
        application.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Run the rewrite Pi ticker application."""

from __future__ import annotations

import os

from .composition import create_application


def main() -> None:
    """Start the selected ticker sink until a process interrupt arrives."""
    os.environ.setdefault("TICKER_MATRIX_REFRESH_HZ", "120")
    os.environ.setdefault("TICKER_PWM_BITS", "8")
    application = create_application()
    try:
        application.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Run the rewrite Pi ticker application."""

from __future__ import annotations

from .composition import create_application


def main() -> None:
    """Start the selected ticker sink until a process interrupt arrives."""
    application = create_application()
    try:
        application.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

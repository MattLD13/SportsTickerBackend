"""Run the rewrite Pi ticker application."""

from __future__ import annotations

from .composition import create_application


def main() -> None:
    """Start the selected ticker sink until a process interrupt arrives."""
    application = create_application()
    # TEMPORARY: force the physical ticker into clock mode while the backend
    # deployment is being repaired. request_mode keeps a local override until
    # the backend acknowledges clock, so stale server mode values cannot switch
    # the display away from clock.
    application.request_mode("clock")
    try:
        application.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

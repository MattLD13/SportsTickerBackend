"""ticker_controller package — sports LED matrix display controller."""

from .controller import TickerStreamer

__all__ = ["TickerStreamer"]


def main():
    ticker = TickerStreamer()
    try:
        ticker.render_loop()
    except KeyboardInterrupt:
        print("Stopping...")
        ticker.running = False

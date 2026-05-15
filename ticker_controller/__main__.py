from .controller import TickerStreamer

if __name__ == "__main__":
    ticker = TickerStreamer()
    try:
        ticker.render_loop()
    except KeyboardInterrupt:
        ticker.running = False

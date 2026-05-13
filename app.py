"""Compatibility entrypoint for the Sports Ticker backend."""

from sports_ticker import create_app, create_runtime, run_server

app = create_app()

if __name__ == "__main__":
    run_server()

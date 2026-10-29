# Ticker 3

Read `docs/architecture/ticker3.md` before you change this folder.

- `contract/` is the only shared code. Every other part imports it. It imports nothing from Ticker 3.
- A feature imports only `ticker3.contract` and `ticker3.sdk`. A test checks this boundary.
- The core names no feature. Built-in features live in `core/builtin/`.
- Ticker 3 imports nothing from `sports_ticker/`, `ticker_core/`, or `backend_ops/`.
- A feature sends records. It does not send display text that depends on the ticker, such as a local time.
- Features share data only through references. A worker never connects to another worker.
- If a template changes, run `python tools/ticker3/preview.py` and inspect the PNGs.
- If the player changes, run `python tools/ticker3/build_fonts.py` only when the font set changes.
- Run `python -m pytest -q tests/python/ticker3` for every change.
- Run `TICKER3_LIVE=1 python -m pytest -q tests/python/ticker3/test_live_features.py` when a feature reads a new upstream.

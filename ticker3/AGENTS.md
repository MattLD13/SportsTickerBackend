# Ticker 3 engine

Read `docs/architecture/ticker3.md` before you change this folder.

- Ticker 3 replaces only the refresh engine. The V2 routes, projections, providers, and every display stay the same.
- The engine publishes through `RefreshService`. It must not change a V2 payload.
- A worker hosts one existing provider without changes. Provider facts stay in `sports_ticker/providers/`.
- The engine names no provider. Provider facts come from `provider_settings_key` and the worker intervals.
- A worker never connects to another worker.
- Run `python -m pytest -q tests/python/ticker3` for every change.
- If the engine changes, `test_engine_equivalence.py` must pass. Do not add fields to its volatile list
  unless the Six ignores them too, as in `ticker_core/protocol/model.py:_display_payload_hash`.
- If recorded provider results change, record them again from the live providers. Do not edit them by hand.

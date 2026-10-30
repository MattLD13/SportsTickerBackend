# Ticker Server

Read `docs/architecture/server.md` before you change this folder. `docs/api.md` lists every route.

| Boundary | Owner |
|---|---|
| Routes, request checks, and authorization | `api/` |
| Device stream | `api/stream.py`, `api/asgi.py` |
| Subscriptions and snapshot publication | `core/engine.py` |
| Worker processes and worker releases | `core/supervisor.py` |
| One provider in one process | `worker/` |
| Messages between the core and the workers | `contract/` |
| Web pages | `web/` |

- A worker hosts one provider from `ticker/server/providers/`. Provider facts stay there.
- The engine names no provider. Provider facts come from `provider_settings_key` and the worker intervals.
- The engine publishes through `RefreshService`. Display data comes only from `ticker/server/projections/`.
- A worker never connects to another worker. A worker loads no route, engine, projection, or Six code.
- The device token names the ticker. Device routes have no ticker ID.
- Run `python -m pytest -q tests/server/core tests/server/worker tests/server/api` for every change.
- If the engine changes, `test_engine_equivalence.py` must pass. Do not add fields to its volatile list
  unless the Six ignores them too, as in `ticker/six/protocol/model.py:_display_payload_hash`.
- If recorded provider results change, record them again from the live providers. Do not edit them by hand.

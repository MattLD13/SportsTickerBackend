# SportsTickerBackend Agent Guide

This repo runs the V2 ticker backend and the Raspberry Pi LED controller.

## Build Properly

Read this file in full before you change code. Read it again after you change this file.

- Find the cause before you edit. Trace input, durable state, API output, client state, and rendered frame.
- Give each fact one owner. Put shared display facts in the V2 domain projection, not in Pi or app heuristics.
- Extend a stable contract when more than one consumer needs a fact. Do not copy parsing or business rules between layers.
- Replace a faulty design. Do not add a compatibility branch, hidden fallback, or special case.
- Remove replaced code and tests in the same change. Remove active imports, fixtures, routes, jobs, and documentation paths.
- Keep provider work, persistence, API projection, runtime scheduling, and rendering separate. Rendering must not fetch data or decide policy.
- Use explicit names for mode, family, kind, ownership, and lifecycle state. Do not infer domain state from display text in a client.
- Make one focused validation across the changed boundary. Render a real 384x32 frame after display changes.
- Remove obsolete test plumbing. Do not create a dummy module to make stale tests pass.

Before a commit, state these facts in the change notes:

1. The owner of the changed fact or behavior.
2. The former path removed or simplified.
3. The real input and output that prove the new path.

## Main Pieces

- `sports_ticker/`: V2 Flask API, provider reads, persistence, pairing, events, and Spotify integration.
- `ticker_core/`: Pi V2 client, caches, runtime, renderers, and matrix drivers.
- `TickerControlApp/`: iOS controller application.
- `tools/`: local render and debug utilities.
- `ticker_data/`: runtime state. Avoid edits except for direct debugging.

## V2 Rules

- Use only `/api/v2` routes and V2 payloads.
- Selectable modes are `sports`, `stock`, `weather`, `music`, `flights`, `airports`, and `clock`.
- A pinned game is `sports_presentation: pinned`, not a display mode.
- Pairing is an effective output state. It is not a stored user mode.
- Alerts, news, connection loss, and updates are overlays. They do not replace the active mode.
- Pi deployments use immutable Git worktrees. Runtime data stays outside a release. Never run `git pull`, reset, or clean in a running release.

## Common Commands

- Compile touched Python: `python -m py_compile path\to\file.py`
- Run focused V2 tests: `python -m pytest -q`
- Render a V2 frame: `python tools\render_rewrite.py --snapshot tests\rewrite\debug\v2_render_snapshot.json --mode sports --item-id nfl-live --no-prefetch --output previews\nfl.png`
- Render the offline panel: `python tools\render_offline_screen.py --out-dir previews\offline`
- Check fleet health: open `http://<backend>/api/v2/health`
- Push a V2 news overlay: `curl -X POST http://<backend>/api/v2/events/news -H 'Content-Type: application/json' -d '{"payload":{"kind":"TRADE","sport":"nhl","from":"VAN","to":"NYR","text":"Miller for Kakko"},"target_ticker_ids":["<ticker_id>"]}'`

## Git Publishing

- When the user asks to publish changes, commit the requested work and push directly to `main`.
- Never create or use a feature branch or draft pull request for a publish request.

## Writing

- Write documentation, comments, docstrings, and commit messages in Simplified Technical English.
- Use 20 words for an instruction sentence and 25 words for an explanation sentence.
- Put a condition before its command. Example: "If the build fails, read the log."
- Use only the modals can, will, and must. Do not use should, may, might, could, or would.
- Use the active voice. Use no semicolons. Use one word for each concept.
- Leave code, identifiers, commands, file paths, and quoted errors exact.

## Development Notes

- Use live or backend render tools for UI verification. Dummy-only tests do not prove a panel change.
- The display target is `384x32`. Tiny layout changes matter. Always render a PNG after UI changes.
- Generated preview PNGs and `__pycache__` files are artifacts. Do not commit bytecode.
- `ticker_core/platform/assets.py` owns durable image cache storage. `ticker_core/assets/` owns planning and memory-only reads.
- OpenF1 provides F1 latest-session data. See https://openf1.org/docs/.

## Adding Racing Content

1. Add the provider contract and source in `sports_ticker/providers/`.
2. Add shared facts in `sports_ticker/providers/sports_display.py` when needed.
3. Add the content family to the V2 projection and scheduler composition.
4. Add one `ticker_core/features/racing/` renderer path without I/O.
5. Update a V2 preview input and render a real PNG.

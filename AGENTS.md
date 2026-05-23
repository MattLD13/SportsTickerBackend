# SportsTickerBackend Agent Guide

This repo powers a sports ticker backend plus a Raspberry Pi LED-matrix style controller/emulator.

## Main Pieces
- `sports_ticker/`: Flask backend, data fetchers, routes, persistence, mode buffers.
- `ticker_controller/`: display renderer/controller for 384x32 LED frames.
- `tools/`: local render/debug utilities. Prefer these over fixture-only scripts.
- `caches/` and `ticker_data/`: runtime data. Avoid editing unless debugging state.
- `ESPstreamer/` and `iOS_Stuff/`: adjacent hardware/app utilities.

## Common Commands
- Compile touched Python: `python -m py_compile path\to\file.py`
- Render live frame: `python tools\fetch_and_render.py --mode indycar --view pin --save indycar_pin_live.png`
- Render racing previews: `python tools\render_racing_previews.py --mode both --out-dir previews`
- Dump backend JSON: `python tools\dump_backend_snapshot.py --mode f1`
- Run pytest suite: `.venv\Scripts\pytest`
- Run pytest with coverage: `.venv\Scripts\pytest --cov=sports_ticker tests/`

## Development Notes
- Use live/backend render tools for UI verification. Avoid adding dummy-only render tests unless they supplement live renders.
- The display target is `384x32`; tiny layout changes matter. Always render a PNG after UI changes.
- Generated preview PNGs and `__pycache__` files are artifacts. Do not commit bytecode.
- The controller caches remote images in `~/ticker/assets` via `download_and_process_logo`.
- OpenF1 is used for F1 latest session data. OpenF1 docs: https://openf1.org/docs/
- **Test Suite Verification**: When modifying core backend logic, API routes, or fetchers, run the pytest suite with `.venv\Scripts\pytest` to verify changes are correct. Add new tests in `tests/` for any new endpoints or core parsing logic. Do not mock configurations globally; rely on `tests/conftest.py`'s automatic filesystem and worker isolation.

## Adding a Racing Mode
1. Add league/mode IDs in `sports_ticker/leagues.py`.
2. Add a fetcher mixin in `sports_ticker/fetchers/` and compose it in `sports.py`.
3. Add mode-buffer dispatch in `sports_ticker/fetchers/sports_modes.py`.
4. Add controller rendering in `ticker_controller/modes/` and wire `controller.py`.
5. Update preview/render tools and render actual PNGs.

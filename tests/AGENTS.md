# Tests

Run the focused checks listed in the task packet.
The test folders mirror the code. A test lives in the folder of the code that it checks:
`tests/shared/`, `tests/server/`, `tests/six/`, `tests/ops/`, and `tests/tools/`.
Native Mini checks live in `tests/mini/`. Fixtures live in `tests/fixtures/`.
Keep each test three levels deep, such as `tests/server/api/test_asgi.py`. Test file names must be unique.

## Commands

| Changed boundary | Focused checks |
|---|---|
| Sports facts | `tests/shared/display/test_sports_display.py`, `tests/server/projections/test_sports_lifecycle.py`, and relevant provider tests |
| Mini hockey | `tests/shared/display/test_mini_hockey_contract.py`, `tests/server/providers/test_hockey_shootout_alert.py`, and `tests/mini/mini_hockey_panes.cpp` |
| Music | `tests/server/spotify/test_spotify.py`, `tests/server/providers/test_music_stale_scope.py` |
| Weather | `tests/server/providers/test_weather_provider.py` |
| Flights and airports | `tests/server/providers/test_flights.py` |
| Golf | `tests/server/providers/test_golf_provider.py`, `test_golf_source.py` |
| Racing | `tests/server/providers/test_racing_live_source.py`, `tests/six/ui/test_racing_renderer.py` |
| Server operations | `tests/ops/` |
| Six platform and updates | `tests/six/platform/` |
| Assets | `tests/six/assets/`, `tests/server/mini_assets/` |
| Agent workflow | `tests/tools/workspaces/` |

Run selected Python paths with `python -m pytest -q <paths>`.
Before every push, run `python -m pytest -m critical -q`.
Before a release or shared domain change, run `python -m pytest -q`.
Compile touched Python files with `python -m py_compile <paths>`.

## Evidence

Use real input/output boundaries and deterministic injected clocks for provider tests.
Mark core invariants with `pytestmark = pytest.mark.critical`.
If display output changes, validate the production renderer at its real panel dimensions.
Do not weaken assertions, add skips, or create dummy modules to conceal broken behavior.
Remove stale test plumbing when its production path is removed.
Keep temporary databases, logs, previews, and bytecode outside Git.
Read `docs/development/testing.md` for hardware diagnostics and full recipes.

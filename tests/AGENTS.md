# Tests

Run the focused checks listed in the task packet.
The Python suite lives in `tests/python/`. Native checks live in `tests/native/`.
Fixtures live in `tests/fixtures/`.

## Commands

| Changed boundary | Focused checks |
|---|---|
| Sports facts | `tests/python/protocol/test_sports_display.py`, `test_sports_lifecycle.py`, and relevant provider tests |
| Mini hockey | `test_mini_hockey_contract.py`, `test_hockey_shootout_alert.py`, and `tests/native/mini_hockey_panes.cpp` |
| Music | `tests/python/integrations/test_spotify.py`, `tests/python/protocol/test_music_stale_scope.py` |
| Weather | `tests/python/protocol/test_weather_provider.py` |
| Flights and airports | `tests/python/protocol/test_flights.py` |
| Golf | `tests/python/protocol/test_golf_provider.py`, `test_golf_source.py` |
| Racing | `tests/python/protocol/test_racing_live_source.py`, `tests/python/features/racing/` |
| Operations | `tests/python/operations/`, `tests/python/platform/` |
| Assets | `tests/python/assets/` |
| Agent workflow | `tests/python/operations/test_agent_workspaces.py`, `test_agent_startup.py`, `test_context_planner.py` |

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

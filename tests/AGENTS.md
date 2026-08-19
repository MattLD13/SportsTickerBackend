# Testing Guide and Procedures

This guide defines the test tiers, command matrix, and verification rules for the test suite.

## Test Tiers

The test suite divides into two tiers.

### Tier 1: Critical Tests

Critical tests validate core architecture, REST API security boundaries, V2 protocol invariants, frame generation, and runtime pacing.
You must run critical tests before every push to `main`.

Run all critical tests:

```powershell
python -m pytest -m critical
```

Critical tests cover:
- `tests/rewrite/api/`: REST API routes, controller token authorization, and pairing.
- `tests/rewrite/application/`: Frame builder, card viewport, and lifecycle state machines.
- `tests/rewrite/runtime/`: Frame pacing, display state, and scroll layouts.
- `tests/rewrite/protocol/`: V2 JSON schema validation, projection invariants, and overlay channels.
- `tests/rewrite/rendering/`: Content family dispatch and catalog routing.
- `tests/rewrite/platform/`: Memory frame sink buffer conversion and health aggregation.
- `tests/rewrite/fleet/`: Hardware profiles and panel capabilities.
- `tests/rewrite/test_modes.py`: Explicit mode definitions and sports filters.
- `tests/rewrite/test_bootstrap.py`: Default registry resolution.
- `tests/rewrite/test_rendering_core.py`: Rendering context and scene dispatch.

### Tier 2: Specific Domain Tests

Specific domain tests validate feature providers, external API parsers, integrations, and platform hardware drivers.
Run specific tests during feature development for the modified domain.

#### Domain Command Matrix

| Domain | Files to Run |
|---|---|
| **Sports Scoreboards** | `python -m pytest tests/rewrite/protocol/test_espn_provider.py tests/rewrite/protocol/test_fotmob_provider.py tests/rewrite/protocol/test_sports_display.py tests/rewrite/providers/` |
| **Golf** | `python -m pytest tests/rewrite/protocol/test_golf_provider.py tests/rewrite/protocol/test_golf_source.py tests/rewrite/features/utility/` |
| **Racing (F1, IndyCar, NASCAR)** | `python -m pytest tests/rewrite/protocol/test_racing_live_source.py tests/rewrite/protocol/test_racing_asset_updater.py tests/rewrite/features/racing/` |
| **Music (Spotify)** | `python -m pytest tests/rewrite/integrations/test_spotify.py` |
| **Flights & Airports** | `python -m pytest tests/rewrite/protocol/test_flights.py` |
| **Clock** | `python -m pytest tests/rewrite/clock/test_clock_renderer.py` |
| **Renderers & Utility** | `python -m pytest tests/rewrite/features/` |
| **Hardware & Operations (BLE, WiFi, OTA)** | `python -m pytest tests/rewrite/operations/ tests/rewrite/platform/` |
| **Assets & Disk Cache** | `python -m pytest tests/rewrite/assets/` |

---

## Testing Procedure

Follow these steps for every change.

### Step 1: Compile Touched Python Files

If you touch Python code, compile every touched file:

```powershell
python -m py_compile path\to\file.py
```

### Step 2: Run the Specific Domain Test

Run the focused domain test suite for the modified area from the Domain Command Matrix.

### Step 3: Render a Real Preview Frame

If you change UI layout, text fonts, or pixel placement, render a real 384x32 PNG image:

```powershell
python tools\render_rewrite.py --snapshot tests\rewrite\debug\v2_render_snapshot.json --mode sports --item-id mlb-live --pinned --no-prefetch --output previews\mlb.png
```

Inspect the output image to verify visual alignment.

### Step 4: Run Critical Tests Before Every Push

Before you commit and push to `main`, run the critical test suite:

```powershell
python -m pytest -m critical
```

If any critical test fails, fix the failure before you push.

### Step 5: Run Full Test Suite

Before a release or after changing shared domain models, run the complete suite:

```powershell
python -m pytest -q
```

---

## Rules for Adding New Tests

1. Mark core invariant tests with `pytestmark = pytest.mark.critical`.
2. Do not add mock network calls without deterministic injected clocks.
3. Keep tests focused on real input and output boundaries.
4. Remove stale tests when you remove code or routes.

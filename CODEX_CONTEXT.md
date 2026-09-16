# Codex Context: Per-Ticker Schedules

This branch contains the per-ticker weekly schedule feature and the app mode override behavior.

Branch: `codex/schedule-mode-overrides`
Base feature commit: `ab11dd9`

## What changed

- Each ticker owns recurring weekly schedule blocks and live-game conditions.
- Schedule blocks use the ticker timezone and `days_of_week` values from Monday `0` through Sunday `6`.
- A block can select any supported V2 mode, including `sports`, `stock`, `weather`, `music`, `flights`, `airports`, and `clock`.
- A live-game condition can change scheduled sports output to `live` when its threshold matches.
- Pinned sports output always wins over schedule conditions.
- An app override wins over time blocks and conditions until the next schedule transition.
- Selecting a mode in the iOS app starts the per-ticker override automatically. The app sends `schedule_override: true` with the settings update.
- Selecting a flight submode also starts the override.
- The connection indicator shows yellow `Connected • Schedule` only for an active time block or condition. An app override shows the normal green connected state.
- The old global dashboard schedule route and active global schedule UI were removed.

## Ownership

- `sports_ticker/domain/schedule.py` owns schedule block and condition contracts.
- `sports_ticker/fleet/repository.py` owns durable per-ticker schedule state and override expiry.
- `sports_ticker/application/schedule.py` owns precedence and effective settings.
- `sports_ticker/api/routes.py` owns the authorized ticker-scoped schedule API.
- `TickerControlApp/TickerControl/ContentView.swift` owns mode-click overrides and connection status.
- `TickerControlApp/TickerControl/TickerScheduleView.swift` owns native schedule editing UI.
- Rendering code must not fetch schedule data or decide schedule policy.

## API surface

Use these V2 routes with a controller authorization token:

```text
GET    /api/v2/tickers/<ticker_id>/schedule
POST   /api/v2/tickers/<ticker_id>/schedule/blocks
PATCH  /api/v2/tickers/<ticker_id>/schedule/blocks/<block_id>
DELETE /api/v2/tickers/<ticker_id>/schedule/blocks/<block_id>
POST   /api/v2/tickers/<ticker_id>/schedule/conditions
PATCH  /api/v2/tickers/<ticker_id>/schedule/conditions/<condition_id>
DELETE /api/v2/tickers/<ticker_id>/schedule/conditions/<condition_id>
PATCH  /api/v2/tickers/<ticker_id>
```

The final route accepts `schedule_override` at the top level. The app sends it beside `display_settings`, not inside `display_settings`.

## Validation already completed

- `python -m pytest tests/rewrite/api/test_schedule.py -q` passed with 3 tests.
- `python -m pytest -m critical` passed with 121 tests.
- The full suite had two unrelated pre-existing import failures in legacy utility and weather tests.
- Windows did not have Swift or Xcode, so the iOS target needs validation on the MacBook.

## MacBook Codex prompt

Paste the following prompt into Codex after opening this branch:

```text
You are continuing work on the SportsTickerBackend branch codex/schedule-mode-overrides.

Read CODEX_CONTEXT.md and AGENTS.md first. Inspect the committed schedule changes before editing. Do not push to main. Do not change unrelated working-tree files.

Validate the iOS app in TickerControlApp with Xcode. Confirm that the project includes TickerScheduleModels.swift and TickerScheduleView.swift. Build the app, then test against the configured V2 backend and a paired ticker.

Test this exact behavior:
1. Open a ticker settings card and tap Schedule.
2. Create a recurring weekly block in the ticker timezone.
3. Confirm that the ticker enters the scheduled mode at the block start and the app shows yellow Connected • Schedule.
4. While the schedule is active, open Modes and tap Stocks or another mode.
5. Confirm that the app sends one PATCH containing display_settings and top-level schedule_override: true.
6. Confirm that the ticker immediately uses the selected mode, the schedule indicator returns to the normal green connected state, and polling does not undo the selection.
7. Confirm that the override expires at the next schedule transition and the recurring rule resumes.
8. Test a sports live-game condition, including the pinned-game case. A condition must not override a pinned game.

If the build fails, identify whether the failure is caused by this branch or by the local Xcode/project environment. Fix only branch-related issues, add focused tests where practical, and report the exact build and runtime results. Do not redesign the schedule model without asking first.
```

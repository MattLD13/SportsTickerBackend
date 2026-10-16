# Mini shootout display and response storage

Date: 2026-10-15

Release: `mini-1.3.8`

## Frozen game data

The physical Mini remains connected to `lehigh-guest` and receives HTTP 200 responses.
The former firmware repeatedly reports `InvalidInput` while retaining the last valid game page.
Serial diagnostics locate overwritten JSON fields within responses between 88 KB and 108 KB.

The pinned Arduino core uses `uint16_t oldLen` inside `String::changeBuffer`.
`HTTPClient::getString` grows a `StreamString` when the server omits `Content-Length`.
Growth beyond 65,535 bytes truncates the retained length and overwrites earlier response bytes.
The parser correctly rejects the corrupted document.

The data transport now writes decoded HTTP bytes into a bounded PSRAM buffer.
The buffer uses `size_t` lengths and accepts at most 512 KiB.
The transport checks write failures and the declared response length before parsing.
The runtime commits only valid JSON and returns the actual parse result.
Serial statistics and heartbeat metrics expose response size, transfer result, HTTP status, and JSON failures.
The firmware does not log response contents or pairing codes.

## Hockey shootouts

The backend `nhl_shootout_display` projection continues to own the shootout lifecycle and visible rounds.
The Mini consumes `displayRounds`, `nextSide`, `roundLabel`, and attempt states.
Green markers indicate goals. Red markers indicate misses. Yellow markers identify the next shooter.
Gray markers indicate pending attempts. Attempts marked `not_taken` remain blank.
The Mini retains the full `R10-12` label and uses the available footer width.
Completed shootouts retain their results. Playoff third overtime retains its overtime display.

## Number sign

The former shared PANE `#` contains five columns. The Mini reads only three columns.
The Mini now measures and draws each glyph using its exported source width.
The five-column number sign retains both vertical strokes and both crossbar extensions.
The generator validates row dimensions and exports glyph widths.

## Football footer spacing

The Mini uses a one-pixel word space in the compact font.
`3RD & 6` measures 23 pixels. `4TH & 15` measures 27 pixels.
Both labels fit the 28-pixel footer on one line.
Longer labels retain the existing two-row layout.
The away possession icon moves two pixels left. The home possession icon moves two pixels right.

## Validation

- Native production renderer checks cover initial rounds, the next shooter, round 12, completed attempts, and playoff third overtime.
- A captured NHL event ledger supplies the completed shootout case.
- Native response tests append 210,000 text bytes in 1,024-byte chunks and verify exact bytes and filtered parsing.
- Buffer tests verify allocation failure and the response size limit.
- Real Mini telemetry observes a 92,669-byte live response with zero JSON failures across 49 samples in 100 seconds.
- Real Mini telemetry retains the verified 200 Hz panel profile.
- Production Mini render code generates 64x32 previews. The main renderer generates real 384x32 references.
- Physical frame captures match all 6,144 RGB bytes for shootout, number-sign, and football layout checks.
- Each temporary frame check restores normal live rendering.
- All 599 Python tests pass. The critical suite passes 269 tests.
- The firmware build, native checks, Ruff, scoped Mypy, and shared drawing-data checks pass.

## Change notes

Owner: The backend owns shootout facts. The Mini protocol adapter owns presentation mapping and response storage.
The shared PANE font owns the number sign and its width.

Former path: Remove growing Arduino String storage from the data fetch.
Replace numeric attempt states, clipped round labels, and fixed-width glyph clipping.

Real input: Live Mini responses, the captured NHL event ledger, and canonical shootout projections.
Real output: Valid large responses, explicit shootout markers, complete round labels, and two visible number-sign strokes.

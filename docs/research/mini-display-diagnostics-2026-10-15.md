# Mini display timing and serial frame capture

Date: 2026-10-15

## Implementation

`mini-1.3.6` adds presentation-based timing and on-request frame capture.
The matrix adapter mirrors existing drawing operations and preserves the original DMA driver calls.
The runtime records pane identity from V2 content IDs.
The backend receives aggregate display telemetry with normal heartbeats.
The USB utility saves live statistics, completed visit durations, exact pixels, and PNG previews.

The change replaces blocking serial line reads with bounded incremental input.
Capture packets fit the Mini USB transmit buffer and wait for available output space.
Pixel transfer does not pause page rotation or select a different game.

Read [the V1 contract](../contracts/mini-display-diagnostics-v1.md) for command and pixel semantics.

## Physical checks

The development build ran on the connected ESP32-S3 and its matrix.
A 60-second capture completed 20 images and 30 statistics samples without protocol errors.
Every image passed the complete 6,144-byte checksum.
The sample window contained 44 completed timed visits.
Their configured target was 1,000 milliseconds.
Their measured mean was 1,340.577 milliseconds. The measured range was 185.824 to 3,005.268 milliseconds.
These results describe that sample and current device settings.
Network work still blocks parts of the Mini scheduler. Instrumentation exposes its effects without changing that policy.

The lifetime mean render time measured 3,525 microseconds at the last sample.
The highest recorded render time measured 12,901 microseconds.
One live snapshot copied and checked its pixels in 611 microseconds.

A temporary RGB888 test pattern completed a byte-for-byte round trip through the real renderer and serial capture.
All 6,144 returned bytes matched the input. The test restored normal live rendering.
The real main ticker projection also produced a 384x32 reference PNG.
Generated images and raw captures stay outside Git under `previews/mini-diagnostics/`.

## Automated checks

The full Python suite passes 597 tests. The critical suite passes 267 tests.
Eight protocol checks cover packet ordering, corruption, incomplete frames, invalid dimensions, and saved image bytes.
The production portable C++ header passes native checks on the real Pi.
Those checks cover clipping, front-buffer retention, redraw timing, long uptime, overlays, and bounded visit history.
Ruff, scoped Mypy, Python compilation, and the ESP32 firmware build pass.
CI runs the native display check with the existing runtime verification.

## Change notes

Owner: The matrix driver owns presented pixels and timestamps. The runtime owns explicit pane context.
Former path: Replace blocking serial reads and heartbeat-only display observation with bounded commands and actual presentation measurements.
Real input: Live V2 games, existing render operations, and a temporary RGB888 verification pattern.
Real output: Measured pane durations, checksum-verified pixel matrices, PNGs, and heartbeat aggregates.

## Published release check

Deployment [38811308789](https://github.com/MattLD13/SportsTickerBackend/actions/runs/38811308789) passes all checks.
The Mini downloads and verifies the 1,301,568-byte `mini-1.3.6` image through OTA.
It restarts, reconnects, registers, loads cached sprites, and acknowledges the running release.
The backend clears the update command. App pairing remains active.
The published image also passes the complete RGB888 pattern round trip.
Normal live rendering resumes after the pattern check.

The final 60-second published capture contains 20 valid images and 30 statistics samples, with zero protocol errors.
All samples identify firmware `mini-1.3.6`.
The sample window contains 43 completed timed visits across the current 19-page rotation.
The configured target is 1,000 milliseconds.
Measured dwell averages 1,375.269 milliseconds and ranges from 188.660 to 3,281.070 milliseconds.
The lifetime render mean is 3,196 microseconds. Its maximum is 12,269 microseconds at the last sample.
The last sample reports 151,036 bytes of free internal heap.

Artifacts include `previews/mini-diagnostics/published/gallery.png`, `visits.csv`, `stats.jsonl`, and per-frame PNG and matrix files.
The collector sends only `STATS` and `CAPTURE`. It leaves app commands and normal page selection under their existing owners.
All serial collection and pattern test processes finish after validation.

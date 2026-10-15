# Mini display diagnostics V1

## Owners

The matrix driver owns the RGB mirror and presentation timestamps.
The runtime supplies the explicit pane kind, V2 item ID, index, count, and configured duration.
The retained V2 projection owns item identities. Diagnostics do not parse status labels or infer game state.

## Timing

`display_metrics.h` records each actual buffer presentation.
Redraws of the same pane retain its start time.
A different pane closes the previous visit and starts a new visit.
The history retains 16 completed visits. Lifetime counters continue after older visits leave the history.
Timestamps use 64-bit monotonic microseconds.
The timestamp records the driver buffer flip. Optical presentation includes the panel scan latency.
The statistics include current pane age, completed durations, render time, loop gaps, and memory.
`late_visits` counts timed visits that exceed their configured duration by more than 100 milliseconds.
Single-pane modes and overlays have no automatic duration target.
Frame counts measure application submissions. The matrix driver independently refreshes the physical panel.

The heartbeat includes bounded aggregates under `metadata.display_metrics`.
The heartbeat does not include screen pixels or visit history.

## USB commands

`STATS` returns one `MINI_STATS:` line followed by JSON.
The object contains `v`, `firmware`, and `display`.
The display object includes the current pane, lifetime counters, and recent visits.
Pane indices start at zero. Gallery page numbers start at one.

`CAPTURE` snapshots the last presented frame without changing the display or scheduler.
It returns these records:

1. `MINI_FRAME_BEGIN:` followed by JSON metadata.
2. 384 `MINI_PIX:<capture-id>:<byte-offset>:<hex-bytes>` records.
3. `MINI_FRAME_END:<capture-id>:<fnv1a32>`.

Capture IDs and checksums use eight hexadecimal digits. Offsets use four hexadecimal digits.
Each pixel record contains 16 bytes, encoded as 32 hexadecimal digits.
The complete RGB888 image contains 6,144 bytes in row order, from the top left.
Every pixel contains red, green, and blue bytes in that order.
The begin record contains dimensions, checksum, firmware version, pane identity, frame number, brightness, and capture time.
The receiver rejects missing, duplicate, malformed, mismatched, and corrupt packets.
It saves a frame only after its complete checksum passes.

The transfer sends one small record per runtime tick when serial output has space.
A transfer expires after 30 seconds. Serial input consumes complete commands without waiting for a missing newline.
Timing collection stays active without a USB reader. Pixel transfers run only after a request.

## Pixel meaning

The mirror receives the same RGB888 values as the panel driver, including its RGB565 expansion.
It follows both drawing buffers and changes its front buffer at presentation.
A separate snapshot preserves one coherent frame throughout transmission.
Two mirror buffers use 12,288 PSRAM bytes. The first capture allocates another 6,144 PSRAM bytes.
If PSRAM allocation fails, diagnostics report capture unavailable and keep the ticker running.

Captured pixels precede panel gamma conversion and brightness modulation.
They prove the software image sent to the driver. Electrical faults, wiring, flicker, and emitted colors require optical inspection.

## Capture utility

```powershell
python tools/capture_mini.py --port COM11 --duration 60 --output previews/mini-diagnostics
```

The utility saves statistics JSONL, completed visits CSV, a summary, and exact 64x32 PNGs.
Each capture includes a JSON pixel matrix, a 32-row hexadecimal matrix, and an enlarged preview.
`gallery.png` shows recent captures together.
CSV summaries include visits that finish after the first statistics sample.
Current pane age remains available for visits that have not finished.

The utility observes the live display. It sends no app commands, game data, or display-mode changes.

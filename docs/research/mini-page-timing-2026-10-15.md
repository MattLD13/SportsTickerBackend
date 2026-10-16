# Mini page timing and hockey penalty layout

Date: 2026-10-15

Release: `mini-1.3.9`

## Measured cause

The configured scroll value is `0.03`. The Mini maps this value to a three-second page duration.
Ten rotating pages on `mini-1.3.8` average 4.994 seconds.
The shortest page lasts 4.028 seconds. The longest page lasts 5.831 seconds.
Registration, data requests, heartbeats, and firmware receipts run on the display task.
The task waits for network I/O before checking the next page deadline.
Logo completion and list changes also reset the former page timestamp.

## Runtime ownership

The network worker owns HTTP requests and response storage during transfer.
Two single-entry queues transfer one request object between the display task and the network worker.
Only the display task applies payloads, settings, pairing state, firmware receipts, and rendered frames.
The worker never reads the active JSON document or modifies display state.
The existing network mutex serializes TLS transfers with sprite downloads and firmware installation.

The displayed frame owns its page start time.
Score refreshes and list reordering retain the visible game identity and deadline.
Logo completion fills the cache without moving the selected game backward.
A new game frame starts a new full duration.
Pinned games and firmware overlays retain their existing lifecycle behavior.

The scheduler requests a fresh snapshot during the last second of a rotating pane.
It allows one prefetch per displayed pane and one network job at a time.
The screen uses the last complete snapshot if a request remains active at the deadline.
Other modes and pinned games retain the normal polling interval.
Heartbeat scheduling takes priority when its interval expires.

## Hockey penalty layout

The backend continues to own penalty clocks, jersey numbers, and formatted labels.
The Mini consumes the existing structured penalty list from the domain projection.
Each row contains one complete clock and jersey number, separated by two blank pixels.
The clock trims empty glyph columns and uses normal letter spacing when the row fits.
A longer clock uses compact clock spacing and retains normal jersey-number spacing.
`0:45 #88` and `10:00 #20` each occupy one 28-pixel line.
Two penalties use separate complete rows, including penalties with equal clocks.
The protocol filter includes `timeRemaining` and `jerseyNumber` for each penalty.
The number sign retains its full crossbars and five-column width.

## Validation

A physical 100-second run observes 26 timed panes from 3.003671 to 3.004802 seconds.
The mean duration is 3.004253 seconds. The run reports no frame capture errors.
A network request lasts 3.079 seconds while page rotation continues independently.
The physical device retains the 200 Hz panel profile and reports zero JSON failures.

Native checks cover the actual frame deadline, prefetch window, score refresh, list reordering, and pin suppression.
Native renderer checks cover single-line two-digit penalties and stacked equal-clock penalties.
The preview set includes the captured Rangers power-play replay and real 384x32 main ticker references.
Physical captures match all 6,144 submitted RGB bytes for single, stacked, and captured penalty panes.
The final 45-second check observes ten panes from 3.004080 to 3.005023 seconds during requests lasting 3.164 seconds.
The full Python suite passes 599 tests. The critical suite passes 269 tests.
The firmware build, native timing checks, native renderer checks, Ruff, scoped Mypy, and drawing-data checks pass.

## Change notes

Owner: The Mini network worker owns transport. Display metrics own the visible page deadline.
The backend owns hockey penalty facts. The Mini renderer owns footer spacing and row breaks.

Former path: Remove synchronous polling and firmware receipts from the display task.
Remove the separate page timestamp and asset-driven timer resets.
Remove twelve-character clipping from hockey penalty labels.

Real input: Live server responses, physical Mini visit telemetry, and a captured NHL penalty replay.
Real output: Three-second pane rotation during active requests and complete two-digit penalty labels.

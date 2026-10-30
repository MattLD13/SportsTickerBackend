# Raspberry Pi ticker rewrite

`ticker.six` is the Ticker Six application for the Raspberry Pi. It owns the device code between a backend response and the LED panels.

`ticker.panel` in `shared/ticker/panel/` draws the frames. Ticker Server uses the same package for its live demo, so the server holds no Six device code.

The golden corpus in `tests/fixtures/six_golden/` records the panel pixels of every card for fixed inputs. `tools/rendering/six_golden.py` checks them.

## Ownership

| Package | Responsibility |
| --- | --- |
| `protocol` | Parse backend responses and perform backend requests. |
| `runtime` | Choose visible content and control display timing. |
| `app` | Run the frame loop, the poller, and the update flow. |
| `platform` | Store device identity, run Wi-Fi and Bluetooth setup, and run operating system commands. |
| `drivers` | Present complete frames to hardware, memory, or the emulator. |

## Performance history

`platform.performance.TickerPiLogger` writes bounded JSONL history to `<TICKER_DATA_DIR>/logs/ticker-performance.jsonl`.

The logger aggregates frame timing, render work, hardware presentation, FPS, brightness, modes, overlays, panel size, and system health.
It also aggregates WebSocket connections, reconnects, message counts, message bytes, sequence progress, and client decode time.

The logger samples process CPU, RSS, load, and Pi temperature in its writer thread. The frame loop performs memory aggregation only, then writes one window record every ten seconds.

The logger rotates five files at ten megabytes each. Stream counts appear inside each `window` record.
The file stays on the Pi. Copy it from `<TICKER_DATA_DIR>/logs/ticker-performance.jsonl` for review.
Read `window`, `poll`, `payload`, and `issue` records with any JSONL tool.

## Device install dependencies

The Pi updater watches `requirements/base.txt`. Keep this file Pi-compatible. Backend-only ASGI packages live in `requirements/server.txt`. CI installs the backend file on the server.

## User modes

The application exposes seven modes: `sports`, `weather`, `music`, `flights`, `airports`, `stock`, and `clock`.

Golf and racing are sports content. A pinned sports item uses `sports_presentation: pinned` and its canonical content ID.

Tracked visitor flights use `flights`. Airport activity uses `airports`. Alerts compose over the active mode.

## Asset cache

Every parsed payload enters the asset coordinator before the scheduler filters its mode.

The short-term content cache stores the last valid display payload. It keeps the ticker useful during a brief backend outage.

The first failed poll adds a connection-lost icon over cached content. Cache expiry replaces content with the offline screen.

The long-term asset cache stores logos, album art, airline marks, and racing cars across restarts.

A bounded decoded-image working set accelerates rendering inside the asset service. It is not the short-term content cache.

All renderers use the same memory-only asset view. Render methods never start downloads or read disk.

## Runtime priorities

The controller resolves one display action for each frame.

Hardware profiles declare the logical frame geometry and supported modes. The full Pi profile uses `384x32`. Custom Pi deployments can set `TICKER_DISPLAY_WIDTH`, `TICKER_DISPLAY_HEIGHT`, `TICKER_DISPLAY_FIT_MODE`, and `TICKER_PANEL_COUNT`.

1. Show an update screen during an active update.
2. Show the pairing code before ordinary content.
3. Keep sleeping panels dark.
4. Show the offline screen after the contact deadline.
5. Show fresh score alerts before scheduled content.
6. Apply fresh news banners over scheduled content.
7. Show static scenes or the scrolling strip.
8. Show the empty screen when no content exists.

## Completion contract

- The Pi uses `GET /data` for boot state and `WS /stream` for display updates. The device token names the ticker.
- The Pi sends telemetry with `POST /heartbeat`. The app changes settings through the controller routes.
- The controller acknowledges reboot commands with `POST /reboot-ack` before it restarts.
- The app keeps mode, brightness, speed, inversion, pairing, sleep, reboot, and update behavior.
- Every renderer returns the same panel pixels for equivalent deterministic inputs.
- Animation receives explicit time values and never reads hidden controller clocks.
- Network and hardware operations stay outside renderers.
- Constructors never start threads or perform network requests.
- The executable can use RGB matrix hardware, an emulator, or an in-memory sink.
- Debug tools can render any scene without starting the full controller.

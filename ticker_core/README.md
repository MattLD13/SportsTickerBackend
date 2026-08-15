# Raspberry Pi ticker rewrite

`ticker_core` is the new Raspberry Pi application. It owns every operation between a backend response and the LED panels.

Legacy modules remain output oracles during parity work. The new entry point will not import them.

## Ownership

| Package | Responsibility |
| --- | --- |
| `protocol` | Parse backend responses and perform backend requests. |
| `runtime` | Choose visible content and control display timing. |
| `rendering` | Route typed scenes and compose exact `384x32` frames. |
| `features` | Render one display family without controller state. |
| `assets` | Plan and warm shared assets before mode filtering. |
| `platform` | Store device identity and run operating system commands. |
| `drivers` | Present complete frames to hardware, memory, or the emulator. |

## Performance history

`platform.performance.TickerPiLogger` writes bounded JSONL history to `<TICKER_DATA_DIR>/logs/ticker-performance.jsonl`.

The logger aggregates frame timing, frame intervals, render work, hardware presentation, percentiles, FPS, brightness, modes, overlays, stale state, inversion, panel size, backend poll timing, response size, and issues.

The logger samples process CPU, RSS, load, and Pi temperature in its writer thread. The frame loop performs memory aggregation only, then writes one window record every ten seconds.

The logger rotates five files at ten megabytes each. Read `window`, `poll`, `payload`, and `issue` records with any JSONL tool.

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

1. Show an update screen during an active update.
2. Show the pairing code before ordinary content.
3. Keep sleeping panels dark.
4. Show the offline screen after the contact deadline.
5. Show fresh score alerts before scheduled content.
6. Apply fresh news banners over scheduled content.
7. Show static scenes or the scrolling strip.
8. Show the empty screen when no content exists.

## Completion contract

- The backend uses `GET /api/v2/tickers/<ticker_id>/data`, `PATCH /api/v2/tickers/<ticker_id>`, and `POST /api/v2/tickers/<ticker_id>/heartbeat`.
- The controller acknowledges reboot commands with `POST /api/v2/tickers/<ticker_id>/commands/reboot/ack` before it restarts.
- The app keeps mode, brightness, speed, inversion, pairing, sleep, reboot, and update behavior.
- Every renderer returns the same panel pixels for equivalent deterministic inputs.
- Animation receives explicit time values and never reads hidden controller clocks.
- Network and hardware operations stay outside renderers.
- Constructors never start threads or perform network requests.
- The executable can use RGB matrix hardware, an emulator, or an in-memory sink.
- Debug tools can render any scene without starting the full controller.

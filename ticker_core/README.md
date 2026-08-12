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

## User modes

The application exposes six modes: `sports`, `sports_full`, `weather`, `music`, `flights`, and `clock`.

Golf and racing are sports content. They scroll in `sports` and fill the panel in `sports_full`.

Flight visitor and airport scenes share `flights`. Alerts compose over the active mode.

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

- The backend keeps the existing `/data`, settings, and flight configuration endpoints.
- The app keeps mode, brightness, speed, inversion, pairing, sleep, reboot, and update behavior.
- Every renderer returns the same panel pixels for equivalent deterministic inputs.
- Animation receives explicit time values and never reads hidden controller clocks.
- Network and hardware operations stay outside renderers.
- Constructors never start threads or perform network requests.
- The executable can use RGB matrix hardware, an emulator, or an in-memory sink.
- Debug tools can render any scene without starting the full controller.

# ESP32 single HUB75 ticker

This firmware drives one 64x32 1/16-scan HUB75 panel from an Adafruit Matrix Portal S3. It uses the V2 ticker data, pairing, and heartbeat routes. It supports sports, stock, weather, music, flights, airports, and clock modes.

## Source layout

`src/main.cpp` only delegates Arduino `setup()` and `loop()` to the mini runtime. The runtime keeps one coordinated translation unit for reliable PlatformIO builds, with hardware and logo-source ownership in real translation units and focused fragments for shared runtime state:

| Path | Ownership |
| --- | --- |
| `src/mini/platform/config.h` | Matrix pins, network defaults, dimensions, and timing constants |
| `src/mini/platform/matrix_driver.h/.cpp` | Matrix construction, double buffering, brightness, and frame presentation |
| `src/mini/platform/connectivity.inc` | Wi-Fi persistence, reconnects, BLE provisioning, and pairing transition |
| `src/mini/protocol/backend.inc` | V2 registration, device identity, and endpoint construction |
| `src/mini/protocol/payload.inc` | V2 payload filtering and runtime state projection |
| `src/mini/assets/logo_sources.h/.cpp` | Central override lookup, server URL selection, and ESPN fallback resolution |
| `src/mini/assets/logo_pipeline.inc` | Logo decoding, cache, retry policy, prepared assets, and background worker |
| `src/mini/rendering/primitives.inc` | Pixel text, clipping, centering, status panels, and page timing helpers |
| `src/mini/features/renderers.inc` | Sports indicators and the seven mode renderers |
| `src/mini/runtime/scheduler.inc` | Heartbeat, polling, Wi-Fi scheduling, and Arduino tick behavior |

The generated fallback override table comes from the backend owner:

```powershell
python tools\generate_mini_logo_overrides.py
```

The server remains authoritative for V2 logo projection. The generated table protects the mini firmware when a deployed server sends an uncorrected source URL.

## Wiring

Use the panel signal names printed beside the HUB75 connector. Connect the following signals:

| HUB75 signal | Matrix Portal S3 GPIO |
| --- | ---: |
| R1 | 42 |
| G1 | 40 |
| B1 | 41 |
| R2 | 38 |
| G2 | 37 |
| B2 | 39 |
| A | 45 |
| B | 36 |
| C | 48 |
| D | 35 |
| CLK | 2 |
| LAT | 47 |
| OE | 14 |
| GND | Matrix Portal GND |

The exact Waveshare P2.5 64x32 panel uses 1/16 scan and does not use E. Leave E unconnected. Connect the panel VCC pins to a separate regulated 5 V supply rated for at least 2.5 A. Connect supply ground, panel ground, and ESP32 ground together. Do not power the panel from an ESP32 GPIO or the USB 5 V rail.

ESP32 GPIO outputs are 3.3 V. If the panel has unreliable colors, sparkles, or blank rows, add a 3.3 V to 5 V buffer such as 74AHCT125 between the ESP32 and HUB75 input. Keep the ribbon wires short. Add the panel maker’s recommended bulk capacitor across panel 5 V and ground.

The pin map targets the Adafruit Matrix Portal S3. A different ESP32-S3 board or adapter requires its own pin map.

## Pair with TickerControl

Set only `BACKEND_URL` in `src/mini/platform/config.h`. The ESP32 derives a stable ticker ID from its eFuse hardware identity. Each board therefore registers as a different ticker on the same server.

At startup, the ESP32 registers a `mini` profile at `/api/v2/devices/register`. The profile declares one `64x32` panel and all seven V2 mode capabilities. The server creates the ticker and pairing code when needed. When the ticker is unpaired, the panel shows its six-digit pairing code. Enter that code in the TickerControl app. The panel renders the selected mode after pairing and sends a heartbeat every 30 seconds.

If Wi-Fi does not connect within 30 seconds, the panel enters Bluetooth setup mode. It shows a six-digit setup PIN and advertises `MiniTicker Setup`. In the TickerControl app, open Wi-Fi setup and enter this PIN. The app sends the new Wi-Fi credentials through the encrypted BLE service. The firmware stores the credentials, reconnects, and then registers with the backend.

The app can change shared settings such as mode, brightness, and scroll speed. Each mode uses a compact 64x32 layout that keeps its primary live values readable.

## Configure and flash

Edit the backend constants at the top of `src/mini/platform/config.h`:

```cpp
WIFI_SSID
WIFI_PASSWORD
BACKEND_URL
```

The first flash uses `WIFI_SSID` and `WIFI_PASSWORD`. Bluetooth-provisioned credentials take precedence after the first successful setup.

The URL must use the V2 route:

```text
http://<backend>/api/v2/tickers/<ticker-id>/data
```

The firmware builds its data and heartbeat URLs after registration. No ticker ID belongs in the firmware source.

In VS Code, install the official PlatformIO IDE extension. Open this `esp32_hub75` folder, then use the PlatformIO Build and Upload commands. No separate ESP32 extension is required.

Use the board connector labeled `UART` in the photo. It is the USB-to-UART port used for the first flash. Use a data-capable USB cable. PlatformIO normally detects the Windows COM port automatically. If it finds more than one port, run `pio device list`, then upload with `pio run -e esp32s3 -t upload --upload-port COMx`.

If automatic upload fails, hold `BOOT`, press and release `RESET`, release `BOOT`, then run the upload again. Use the `USB` connector only for native USB workflows. The `UART` connector is the reliable first-flash choice.

Build and upload from this directory:

```powershell
pio run
pio run --target upload
pio device monitor
```

The firmware refreshes the data every five seconds. Sports pages one shown game at a time. Other modes render the first shown item. The server `scroll_speed` setting controls sports page dwell. The dwell is `scroll_speed × 100` seconds, clamped to one through ten seconds. The default `0.03` value gives three seconds per page.

For hardware testing, set `SOLID_COLOR_TEST` to `true` in `src/mini/platform/config.h`. It cycles red, green, blue, white, and black every 1.5 seconds without using Wi-Fi or the backend. Set it to `false` to restore the ticker loop.

If the backend returns no shown sports items, the panel shows `NO SPORTS`. The existing payload remains visible during a temporary HTTP failure.

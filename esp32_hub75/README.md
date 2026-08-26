# ESP32 HUB75 mini ticker

This firmware drives one 64x32, 1/16-scan HUB75 panel from an Adafruit Matrix Portal ESP32-S3. It reads V2 ticker data, registers itself, supports backend pairing, and sends a heartbeat.

Selectable display modes are `sports`, `stock`, `weather`, `music`, `flights`, `airports`, and `clock`. The firmware uses one compact 64x32 layout for each mode.

## Hardware

Use these parts:

- Adafruit Matrix Portal ESP32-S3
- One 64x32, 1/16-scan HUB75 panel
- Regulated 5 V panel supply rated for at least 2.5 A
- Short HUB75 ribbon cable
- Data-capable USB cable

Connect the HUB75 signals to the Matrix Portal S3 as follows:

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

This panel uses 1/16 scan and does not use `E`. Leave `E` unconnected.

Connect panel VCC to the separate 5 V supply. Connect panel ground, supply ground, and ESP32 ground together. Do not power the panel from an ESP32 GPIO or the USB 5 V rail. Add the panel maker’s recommended bulk capacitor across 5 V and ground.

ESP32-S3 outputs use 3.3 V logic. If colors are wrong or the panel shows sparkles or blank rows, add a 3.3 V to 5 V buffer such as `74AHCT125`. A different ESP32-S3 board requires a different pin map.

## Firmware layout

`src/main.cpp` delegates Arduino `setup()` and `loop()` to the mini runtime. `src/mini/runtime/mini_runtime.cpp` includes the focused runtime fragments into one PlatformIO translation unit.

| Path | Owner |
| --- | --- |
| `src/mini/platform/config.h` | Network defaults, panel pins, dimensions, and timing constants |
| `src/mini/platform/matrix_driver.h/.cpp` | HUB75 construction, double buffering, brightness, and frame presentation |
| `src/mini/platform/connectivity.inc` | Saved Wi-Fi, reconnects, BLE provisioning, and pairing transition |
| `src/mini/protocol/backend.inc` | V2 registration, eFuse device identity, and endpoint construction |
| `src/mini/protocol/payload.inc` | V2 payload filtering and retained runtime state |
| `src/mini/platform/firmware_update.inc` | Manifest checks, SHA-256 download, OTA rollback, and update progress |
| `src/mini/features/renderers.inc` | Sports indicators and all seven mode renderers |
| `src/mini/rendering/primitives.inc` | Text, clipping, centering, status panels, and page timing |
| `src/mini/assets/logo_sources.h/.cpp` | Logo override lookup and fallback URL selection |
| `src/mini/assets/logo_pipeline.inc` | Logo download, decode, cache, retry, and worker task |
| `src/mini/runtime/scheduler.inc` | Startup, polling, heartbeat, Wi-Fi scheduling, and Arduino ticks |

The generated logo override assets are owned by the backend provider data. The generator downloads each override and uses the large ticker's contained PIL preparation path. It embeds each prepared 18x18 RGB565 asset in firmware. If the provider data changes, regenerate the assets from the repository root:

```powershell
python tools\generate_mini_logo_overrides.py
```

Do not edit `src/mini/assets/logo_overrides_generated.h` by hand.

## Configure Wi-Fi and the backend

Edit these constants in `src/mini/platform/config.h` before the first flash:

```cpp
WIFI_SSID
WIFI_PASSWORD
BACKEND_URL
```

Keep real Wi-Fi credentials out of commits. Bluetooth-provisioned credentials take precedence after the firmware stores them in ESP32 NVS.

`BACKEND_URL` is the server base URL, such as `https://ticker.example.com`. The firmware creates these V2 routes after registration:

```text
POST /api/v2/devices/register
GET  /api/v2/tickers/<ticker-id>/data
POST /api/v2/tickers/<ticker-id>/heartbeat
GET  /api/v2/tickers/<ticker-id>/firmware
POST /api/v2/tickers/<ticker-id>/updates/ack
```

The firmware derives a stable device ID from the ESP32 eFuse MAC. It sends an `esp32s3-...` device ID with a `mini` profile, one 64x32 panel, 16-bit color, OTA capability, and all seven mode capabilities. The server returns the ticker ID, pairing state, and pairing code. No ticker ID belongs in the firmware source.

## OTA updates

The custom 8 MB partition table contains two 2 MiB OTA application slots, an OTA data partition, and 3.625 MiB of LittleFS storage for logos. The firmware rejects images larger than the inactive 2 MiB slot.

The production backend loads a complete manifest from `TICKER_FIRMWARE_MANIFEST_PATH` or the `TICKER_MINI_FIRMWARE_*` environment variables. The deploy workflow builds the mini binary, stores it in the server firmware directory, and serves it from the manifest HTTPS URL. The manifest contains `version`, `target`, `hardware`, `binary_url`, `size`, and `sha256`. A release request uses `POST /api/v2/tickers/<ticker-id>/updates` with the existing deployment token. The mini reads the pending V2 update command, fetches `GET /api/v2/tickers/<ticker-id>/firmware`, verifies the target, hardware, HTTPS URL, size, HTTP status, content length, image structure, and SHA-256, then activates the inactive slot.

Every successful `main` deployment requests the current mini firmware through the same V2 update route. The mini downloads the release automatically after it reconnects to Wi-Fi.

Manual workflow dispatch accepts `ota_ticker_id` when one ticker needs a targeted release request.

The mini renders checking, downloading, installing, and failure states. It stores the pending version in NVS and validates the new boot before acknowledgement. Transient transfer failures retry after 60 seconds. A boot rollback blocks that exact version to prevent a reboot loop.

## Pairing and startup

At boot, the firmware loads saved Wi-Fi credentials, initializes the panel and logo worker, then connects to Wi-Fi. It registers with the backend and fetches data every five seconds. It sends a heartbeat every 30 seconds.

If the server reports an unpaired ticker, the panel shows the six-digit backend pairing code. Enter that code in TickerControl. The firmware keeps the code in NVS and stops showing the pairing screen after the server reports `paired: true`.

If Wi-Fi stays disconnected for 30 seconds, the firmware turns Wi-Fi off and starts encrypted BLE provisioning. The panel shows a six-digit setup PIN. The device advertises as `MiniTicker Setup`. In TickerControl, open Wi-Fi setup and submit the PIN with the new credentials. The firmware stores the credentials, reconnects, and registers again.

The BLE provisioning service uses the service UUID below:

```text
8F8B0001-6E2A-4D8A-9F31-8D4B77F0B001
```

For repeatable desktop provisioning tests, use the repository helper. Set the password through an environment variable instead of passing it as a command-line argument:

```powershell
$env:MINI_TICKER_WIFI_PASSWORD = "your-password"
python tools\mini_ticker_test_pairer.py --ssid "your-ssid" --backend-url "https://ticker.example.com"
```

The helper reads the setup PIN from the 115200 baud serial log, sends encrypted credentials, waits for the backend pairing code, and exchanges that code.

## Build, flash, and monitor

Install the official PlatformIO IDE extension or the PlatformIO CLI. The project uses the `esp32s3` environment and the `adafruit_matrixportal_esp32s3` board.

Run these commands from `esp32_hub75`:

```powershell
pio run
pio run --target upload
pio device monitor
```

The serial monitor uses 115200 baud. Only selected diagnostics, such as reset and heartbeat logs, write to both `Serial` and `Serial0`. Registration, BLE, and solid color-test logs use `Serial` only.

Use the board connector labeled `UART` for the first flash. Use a data-capable cable. If PlatformIO finds multiple ports, list them and select the correct COM port:

```powershell
pio device list
pio run -e esp32s3 -t upload --upload-port COMx
```

If upload does not start, hold `BOOT`, press and release `RESET`, release `BOOT`, then run the upload command again. Use the `USB` connector for native USB workflows. The `UART` connector is the reliable first-flash path.

## Display behavior

Sports mode shows one shown game at a time and rotates through the shown games. Item-based modes render the first shown item in their content array. Clock mode renders the configured time directly.

The backend `scroll_speed` setting controls sports page dwell. The firmware treats it as seconds per scroll pixel, converts it to page dwell, and clamps the result to one through ten seconds. The default `0.03` value gives three seconds per page.

Sports pages render scores, team logos, status, and sport-specific live indicators:

- Football: possession and down-distance
- Baseball: inning, count, bases, and outs
- Hockey: power play and empty net
- Soccer: red cards

Generated override logos load directly from firmware. Other logos load from the V2 payload or ESPN fallback URLs, decode to 18x18 pixels, and enter the RAM working set. LittleFS stores up to 256 downloaded logo records in `/logo_cache_v9.bin`. A first load can show `DOWNLOAD ASSETS` while the background worker fetches non-override logos.

The other layouts show these fields:

- Weather: temperature, condition, humidity, and wind
- Music: track, artist, playing state, and progress
- Flights: flight ID, route, ETA, status, and progress
- Airports: next arrival, next departure, and airport weather
- Stock: symbol, price, percent change, and daily change
- Clock: local date and time from the configured timezone and NTP

During a temporary HTTP or JSON failure, the firmware keeps the last valid sports page when one exists. Initial failures show a short status message such as `WIFI LOST`, `REGISTER`, `HTTP 500`, `JSON ERROR`, or `NO SPORTS`.

## Hardware tests

Set `SOLID_COLOR_TEST` to `true` in `src/mini/platform/config.h` to cycle red, green, blue, white, and black every 1.5 seconds. This test bypasses Wi-Fi, registration, and rendering data.

Set `FORCE_PAIRING_TEST` to `true` to start BLE provisioning at boot. Use this test for the pairing path without waiting for the 30-second Wi-Fi timeout.

Set both test switches to `false` before normal ticker operation. Reflash after changing either switch.

## Troubleshooting

- If the panel stays blank, verify separate 5 V power, common ground, the ribbon orientation, and the `UART` pin map.
- If colors are swapped or unstable, verify the panel’s HUB75 signal labels and add a `74AHCT125` level buffer.
- If the panel shows `WIFI...`, verify the SSID, password, 2.4 GHz network, and saved credentials in NVS.
- If the panel shows `REGISTER`, verify `BACKEND_URL` and that the server exposes `/api/v2/devices/register`.
- If the panel shows `NO <mode>`, verify that the selected V2 mode has at least one shown content item.
- If the panel shows `DOWNLOAD ASSETS`, keep Wi-Fi available while the logo worker downloads and caches images.
- If the panel enters BLE setup, read the setup PIN from the panel or the 115200 baud serial log and complete Wi-Fi provisioning.

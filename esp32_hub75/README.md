# ESP32 single HUB75 ticker

This firmware drives one 64x32 1/16-scan HUB75 panel from an ESP32-S3 DevKitC. It uses the V2 ticker data, pairing, and heartbeat routes. It supports the sports mode only and shows one game per page.

## Wiring

Use the panel signal names printed beside the HUB75 connector. Connect the following signals:

| HUB75 signal | ESP32 GPIO |
| --- | ---: |
| R1 | 4 |
| G1 | 5 |
| B1 | 6 |
| R2 | 7 |
| G2 | 15 |
| B2 | 16 |
| A | 10 |
| B | 11 |
| C | 12 |
| D | 13 |
| CLK | 17 |
| LAT | 18 |
| OE | 8 |
| GND | ESP32 GND |

The exact Waveshare P2.5 64x32 panel uses 1/16 scan and does not use E. Leave E unconnected. Connect the panel VCC pins to a separate regulated 5 V supply rated for at least 2.5 A. Connect supply ground, panel ground, and ESP32 ground together. Do not power the panel from an ESP32 GPIO or the USB 5 V rail.

ESP32 GPIO outputs are 3.3 V. If the panel has unreliable colors, sparkles, or blank rows, add a 3.3 V to 5 V buffer such as 74AHCT125 between the ESP32 and HUB75 input. Keep the ribbon wires short. Add the panel maker’s recommended bulk capacitor across panel 5 V and ground.

The pin map targets the pictured ESP32-S3 board. A different ESP32-S3 board or adapter requires its own pin map.

## Pair with TickerControl

Set only `BACKEND_URL` in `src/main.cpp`. The ESP32 derives a stable ticker ID from its eFuse hardware identity. Each board therefore registers as a different ticker on the same server.

At startup, the ESP32 registers a `mini` profile at `/api/v2/devices/register`. The profile declares one `64x32` panel and sports-only capability. The server creates the ticker and pairing code when needed. When the ticker is unpaired, the panel shows its six-digit pairing code. Enter that code in the TickerControl app. The panel switches to sports after pairing and sends a heartbeat every 30 seconds.

The app can change shared sports settings such as brightness and scroll speed. The panel displays `SPORTS ONLY` when the app selects another mode.

## Configure and flash

Edit the three constants at the top of `src/main.cpp`:

```cpp
WIFI_SSID
WIFI_PASSWORD
DATA_URL
```

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

The firmware refreshes the data every five seconds. It pages one shown `sports`, `golf`, or `racing` item at a time. The server `scroll_speed` setting controls page dwell. The dwell is `scroll_speed × 100` seconds, clamped to one through ten seconds. The default `0.03` value gives three seconds per page.

For hardware testing, `SOLID_COLOR_TEST` is temporarily enabled in `src/main.cpp`. It cycles red, green, blue, white, and black every 1.5 seconds without using Wi-Fi or the backend. Set it to `false` to restore the ticker loop.

If the backend returns no shown sports items, the panel shows `NO SPORTS`. The existing payload remains visible during a temporary HTTP failure.

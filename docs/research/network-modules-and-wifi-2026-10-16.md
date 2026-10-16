# Transport modules and Wi-Fi options

## Changed owners

`NetworkWorker` owns the request and result queues and background HTTP execution.
`NetworkGate` owns the shared TLS mutex. Allocation failure blocks network access.
`FirmwareUpdater` owns manifest validation, download, image verification, persistent update receipts, boot validation, and acknowledgement.
`http_diagnostics.cpp` owns TLS failure logging.
The runtime owns response application, pairing, reconnect policy, retained JSON, and display scheduling.

The former network worker and updater depended on textual include order and unrelated runtime globals.
The compiled modules receive explicit dependencies. The updater captures the device identity before launching its task.
The runtime supplies registration state and receives a redraw request from the updater.
The updater does not call a renderer.

The data worker retains core 0, priority 1, an 8,192-byte stack, and two queues with one slot each.
The updater retains core 0, priority 1, and a 12,288-byte stack.
TLS clients retain the shared mutex, verified certificates, HTTPS DNS, timeouts, and request order.
The change keeps the existing HTTP connection policy.

`TickerHTTPClient` owns URLSession execution and authorized request construction.
`TickerHTTPTransport` exposes suspended tasks with explicit resume and cancellation.
The view model selects credentials and owns task lifetime, stale-response checks, callbacks, and timers.
The former direct `URLSession.shared` call sites now use the injected transport.
The default transport still uses `URLSession.shared`.

## Baseline on the physical Mini

The 35-second capture records 12 frames, 18 telemetry samples, and 11 timed visits.
Visits last 3,004.333 to 3,004.772 milliseconds. The capture reports no errors.
The device displays 20 games and receives about 30,121 bytes per data response.
Observed completed requests range from 2,474 to 2,818 milliseconds.
RSSI ranges from -59 to -58 dBm. Sampled free heap reaches 43,484 bytes during TLS work.
These samples measure application requests, not radio throughput.

The five-second poll interval also permits requests before sports page changes.
Payload size alone does not establish a radio bandwidth bottleneck.

The candidate's successful-request samples record a median 1,947 milliseconds before headers and 239 milliseconds for the body.
The median header share is 89.1%. This stage includes DNS, TCP, TLS, and server work.
Those stages need separate measurement before attributing the delay to one cause.
This comparison does not prove a speed increase from source extraction.

## Validation

The critical Python suite passes 296 tests. The full suite passes 623 tests.
The pinned PlatformIO build compiles the separate network and updater modules.
Static RAM changes from 77,020 to 77,108 bytes. Application flash changes from 1,283,377 to 1,289,633 bytes.
The native updater check runs on the real Pi.
It checks version syntax, every checksum byte, incomplete transfers, wrong targets, wrong hardware, HTTPS, size bounds, and stale acknowledgements.
It also checks matching and mismatched persistent boot receipts.
The device workflow runs this check before reporting firmware build success.

The iOS package adds five HTTP tests for authorization, suspended tasks, cancellation, HTTP status forwarding, and network error forwarding.
The macOS workflow runs these tests and builds the app in Debug and Release configurations.

The physical candidate runs `mini-1.3.12` before the release OTA test.
Its 120-second capture records 39 frames, 59 telemetry samples, and 32 timed visits without capture errors.
All 12 pane identities shared with the baseline retain identical frame hashes.
Timed visits range from 3,004.037 to 3,009.940 milliseconds. Their mean is 3,004.602 milliseconds.
The panel retains 200 Hz refresh. Registration and data requests return 200. JSON failures remain zero.
Telemetry records no uptime reset during that capture.

One earlier capture loses USB contact and returns after a device restart. That capture contains no panic diagnosis.
A 45-second recheck and the later 120-second check complete without another reset.
Serial telemetry now includes the ESP32 reset reason for future diagnosis.
The sampled allocation sizes include active TLS work and do not establish a controlled memory comparison.

Native rejection checks do not prove recovery from a physical power cut during flash programming.
The pinned ESP32 SDK enables bootloader rollback. The updater retains image verification and boot validation before acknowledgement.

## Wi-Fi hardware

| Option | Available improvement | Integration and decision |
| --- | --- | --- |
| Current MatrixPortal ESP32-S3 | Existing 2.4 GHz radio and stable matrix driver. | Keep this board for the present workload. Measure request stages first. |
| MatrixPortal S3 with external antenna | Antenna placement can improve reception near metal or behind a panel. | Closest board replacement. It keeps the S3 processor. Current signal measurements do not prove a reception problem. |
| ESP32-C5-WROOM-1 or WROOM-1U | Dual-band 2.4/5 GHz Wi-Fi 6. The 1U accepts an external antenna. | Candidate for a future radio prototype. It is not a replacement for the current matrix controller without porting. |
| S3 plus C5 through ESP-Hosted | Keeps the display processor and adds a separate dual-band radio. | Requires extra wiring, power, free pins, a host driver, and SDK integration. No ticker speedup is measured. |
| ESP32-C6 | 2.4 GHz Wi-Fi 6. | No 5 GHz benefit. Its main CPU runs up to 160 MHz. It does not provide a simple display upgrade. |

Adafruit documents the [external-antenna MatrixPortal S3](https://www.adafruit.com/product/6475).
Espressif documents the [C5 modules and antenna variants](https://documentation.espressif.com/esp32-c5-wroom-1_wroom-1u_datasheet_en.html).
The [C5 datasheet](https://documentation.espressif.com/esp32-c5_datasheet_en.html) lists dual-band Wi-Fi.
The [C6 specification](https://www.espressif.com/en/products/socs/esp32-c6) lists 2.4 GHz Wi-Fi and processor limits.

The [matrix library support list](https://github.com/mrcodetastic/ESP32-HUB75-MatrixPanel-DMA#supported-esp32-variants) lists ESP32, S2, and S3.
Do not assume that a C5 or C6 runs the current pinned display driver.
Espressif documents [S3 host and C5 coprocessor operation](https://github.com/espressif/esp-hosted-mcu/blob/main/docs/getting-started-mcu.md).
Its Dual SPI test proves that combination can communicate. It does not prove MatrixPortal pin availability or ticker performance.

## Existing software modules

The existing Arduino Wi-Fi library already uses the Espressif radio stack.
[WiFiManager](https://github.com/tzapu/WiFiManager) provides connection setup through a captive portal.
That feature does not establish faster data transfers and overlaps the existing BLE setup flow.

Espressif's [HTTP client](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-reference/protocols/esp_http_client.html) supports persistent connections through a reused handle.
This provides a concrete next experiment for reducing repeated connection work.
The current data worker creates a new TLS client and disables reuse for each request.
Any experiment must preserve HTTPS DNS, certificate checks, bounded memory, sprite serialization, and OTA access.

Wi-Fi sleep is already disabled. Espressif documents the [power-save and latency tradeoff](https://docs.espressif.com/projects/esp-idf/en/v4.4.2/esp32s3/api-guides/wifi.html).
No additional sleep change is available from that setting.

## Next performance experiment

Compare `gate_wait_ms`, `headers_ms`, and `body_ms` on the same board and network.
`headers_ms` includes DNS, TCP, TLS, and server response time. It does not isolate each component.
If header time dominates, compare persistent HTTPS against the current connection policy.
Measure request latency, free heap, largest allocation, reconnect recovery, sprite work, and OTA completion.
Adopt the change only after real hardware results establish its benefit.

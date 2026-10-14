# ESP32 and iOS Module Map

## Baseline

This map records read-only analysis at SOW baseline `a74596046a3672a912ade0dbc7b112d7c167a9d0`.
The SOW documentation baseline is `1d38e4f6879141098011fbe2aaf93c630dcc6045`.
No firmware or iOS files changed during this audit.

## ESP32 Mini

`esp32_hub75/src/mini/runtime/mini_runtime.cpp` defines shared state and textually includes eight `.inc` fragments.
These fragments form one translation unit. Their include order supplies declarations and definitions across files.

The current include order is connectivity, backend protocol, firmware update, rendering primitives, logo pipeline, feature renderers, payload protocol, and scheduler.

| Source | Main responsibility | Split risk |
|---|---|---|
| `platform/connectivity.inc` | Preferences, Wi-Fi, BLE provisioning, and credential handoff. | Callback lifetime, crypto, and shared NVS state. |
| `protocol/backend.inc` | Registration, ticker identity, pairing, HTTP requests, and response routing. | Shared request serialization and identity state. |
| `platform/firmware_update.inc` | Manifest validation, OTA download, rollback, and acknowledgement. | Flash state, task lifetime, and shared runtime access. |
| `rendering/primitives.inc` | Text drawing, sports display policy, paging, pairing, and status panels. | Mixed drawing code and policy ownership. |
| `assets/logo_pipeline.inc` | LittleFS records, decoders, downloads, cache management, and worker tasks. | Decoder globals, locks, borrowed buffers, and allocation lifetime. |
| `features/renderers.inc` | Mode dispatch, pages, status, and update rendering. | Reads payload and shared scheduler state. |
| `protocol/payload.inc` | Retained JSON parsing, filtering, normalization, and state updates. | JSON values borrow memory from the retained document. |
| `runtime/scheduler.inc` | Startup, polling, heartbeat, network transitions, and page timing. | Owns initialization order and task coordination. |

### ESP32 ownership facts

Startup initializes Preferences before OTA, then the matrix, mutexes, and logo worker.
Preserve that order during any translation-unit split.
The logo worker and OTA task currently use core 0.
The runtime owns shared JSON, identity, buffers, decoder state, mutexes, and queue generations.
The logo pipeline allocates cache slots in PSRAM and can allocate up to 256 KiB download buffers.

The lowest-risk first split moves pure text and pixel drawing helpers from `rendering/primitives.inc` into `text_primitives.h` and `text_primitives.cpp`.
Keep sports selection, paging, pairing, and status policy in the existing translation unit.
The new module needs display configuration and drawing access only.

Validate the ESP32 build after each split. Validate heap, task stacks, matrix refresh, and physical panel output on hardware.
Compilation alone does not prove memory stability or DMA behavior.

## iOS controller

`TickerControlApp/TickerControl/ContentView.swift` owns the main dashboard, data types, transport, BLE provisioning, and helper views.
`TickerViewModel` is `@MainActor` and owns server state, selected devices, catalogs, settings, polling, save debounce, and credentials.
It also owns URLSession tasks, device selection, location and SSID reads, Spotify state, and cancellation.
Preserve one view-model instance and its timer lifecycle during view extraction.

The project uses a synchronized Xcode source group. New files under `TickerControl` enter the app target automatically.
The Swift package tests only `DeviceListState.swift` and `TickerScheduleModels.swift`.
The Xcode project has no app test target today.

The lowest-risk first extraction moves `BLEProvisioningCoordinator` intact to a dedicated file.
Preserve CoreBluetooth callback queues, service UUIDs, HKDF-SHA256, AES-GCM, and credential chunking.
A later extraction can move model declarations with `Game.init(content:)` while retaining current normalization.

Validate app Debug and Release simulator builds on macOS. Add API and serialization tests before changing state ownership.
Validate BLE provisioning and reconnect behavior with the ESP32 hardware path.

## Environment limits

The audit host runs Windows and has no `xcodebuild` or Swift compiler.
No physical ESP32, HUB75 matrix, or iPhone validation was available during this map.
See [the revised engineering SOW](../master-engineering-sow.md) for gate requirements.

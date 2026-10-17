# ESP32 and iOS Module Map

## Baseline

This map records current module boundaries after the Gate 6 transport extraction on 2026-10-16.
The SOW documentation baseline is `1d38e4f6879141098011fbe2aaf93c630dcc6045`.
Read [the extraction evidence](platform-modules-2026-10-16.md) for build, pixel, and hardware checks.

## ESP32 Mini

`esp32_hub75/src/mini/runtime/mini_runtime.cpp` defines shared state and textually includes nine `.inc` fragments.
These fragments form one translation unit. Their include order supplies declarations and definitions across files.

The include order is connectivity, backend protocol, presentation, sprite pipeline, feature renderers, diagnostics, payload, network results, and scheduler.
Text drawing, HTTP execution, TLS synchronization, HTTP diagnostics, and OTA compile as separate modules.

| Source | Main responsibility | Split risk |
|---|---|---|
| `platform/connectivity.inc` | Preferences, Wi-Fi, BLE provisioning, and credential handoff. | Callback lifetime, crypto, and shared NVS state. |
| `protocol/backend.inc` | Registration, ticker identity, pairing, HTTP requests, and response routing. | Shared request serialization and identity state. |
| `platform/firmware_update.h/.cpp` | Manifest validation, OTA download, rollback, and acknowledgement. | Flash state, task lifetime, and shared runtime access. |
| `rendering/presentation.inc` | Sports selection, paging, pairing, and status presentation. | Retained JSON and runtime state. |
| `assets/sprite_pipeline.inc` | Validated sprite downloads, LittleFS storage, RAM cache, and worker coordination. | Locks, borrowed buffers, and allocation lifetime. |
| `features/renderers.inc` | Mode dispatch, pages, status, and update rendering. | Reads payload and shared scheduler state. |
| `protocol/payload.inc` | Retained JSON parsing, filtering, normalization, and state updates. | JSON values borrow memory from the retained document. |
| `runtime/network.h/.cpp` | Bounded request ownership and HTTP execution. | Queue ownership and task lifetime. |
| `runtime/network_results.inc` | Response application on the display task. | Retained state and reconnect policy. |
| `platform/network_gate.h/.cpp` | Shared TLS and Wi-Fi renewal exclusion. | Allocation failure and initialization order. |
| `runtime/scheduler.inc` | Startup, polling, heartbeat, network transitions, and page timing. | Owns initialization order and task coordination. |

### ESP32 ownership facts

Startup initializes Preferences before OTA, then the matrix, mutexes, and logo worker.
Preserve that order during any translation-unit split.
The logo worker and OTA task currently use core 0.
The runtime owns shared JSON, identity, buffers, decoder state, sprite mutexes, and queue generations.
`NetworkWorker` owns HTTP queues. `NetworkGate` owns their shared TLS mutex.
`NetworkLease` retains that mutex through client destruction. `TlsClient` owns idempotent socket cleanup.
`FirmwareUpdater` owns OTA state and captures the ticker identity before starting its task.
The sprite pipeline owns PSRAM cache slots and validated immutable sprite transfers.

The first split moves text drawing into `rendering/text_primitives.h` and `rendering/text_primitives.cpp`.
Pure layout and glyph helpers remain separate from the platform adapter.
Sports selection, paging, pairing, and status presentation remain in the runtime translation unit.

Validate the ESP32 build after each split. Validate heap, task stacks, matrix refresh, and physical panel output on hardware.
Compilation alone does not prove memory stability or DMA behavior.

## iOS controller

`ContentView.swift` owns the root view. Models, provisioning, the complete view model, shared style, and screens have separate files.
`TickerViewModel` is `@MainActor` and owns server state, selected devices, catalogs, settings, polling, save debounce, and credentials.
It also owns task lifetime, device selection, location and SSID reads, Spotify state, and cancellation.
`TickerHTTPClient` owns URLSession execution and authorized request construction through an injected transport interface.
Preserve one view-model instance and its timer lifecycle during view extraction.

The project uses a synchronized Xcode source group. New files under `TickerControl` enter the app target automatically.
The Swift package tests device selection, schedules, extracted content models, and hardware profiles against backend fixtures.
The Xcode project has no app test target today.

The first extraction moves `BLEProvisioningCoordinator` intact to `Services/BLEProvisioningCoordinator.swift`.
Preserve CoreBluetooth callback queues, service UUIDs, HKDF-SHA256, AES-GCM, and credential chunking.
Model declarations and `Game.init(content:)` now live in `Models/TickerContentModels.swift` with their existing normalization.

Validate app Debug and Release simulator builds on macOS. Add API and serialization tests before changing state ownership.
Validate BLE provisioning and reconnect behavior with the ESP32 hardware path.

## Environment limits

The audit host runs Windows and has no `xcodebuild` or Swift compiler.
The physical ESP32 and HUB75 matrix pass capture and telemetry checks. No physical iPhone validation is recorded for this extraction.
See [the revised engineering SOW](../master-engineering-sow.md) for gate requirements.

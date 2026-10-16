# Gate 6 build coverage and platform modules

## Owners

The device workflow owns firmware and iOS build validation.
The static workflow owns Python source checks.
Firmware drawing modules own pixels. Runtime modules own scheduling, shared state, and network coordination.
The iOS view model owns selection, tokens, timers, and request lifetime.

## Build coverage

The former workflows ran only for pull requests and manual dispatch.
Direct `main` pushes now trigger checks for platform, contract, and shared drawing changes.
The iOS workflow runs package serialization tests and simulator builds in Debug and Release configurations.
The firmware workflow keeps its pinned PlatformIO build.

The first change adds validation before any platform source extraction.
Existing application and firmware builds provide the baseline for later module moves.
The critical Python suite passes 296 tests before this change.

## Module boundaries

Extract text drawing before moving runtime state or network tasks.
Use explicit drawing surfaces instead of global matrix access in the drawing module.
Keep hardware initialization and frame presentation in their current owners.

Move complete iOS declarations into model, provisioning, view-model, and screen files.
Keep callbacks, request timing, credentials, and view-model instances in their current owners.
Validate shared models against backend contract fixtures on the macOS runner.

## iOS extraction

The baseline firmware, Debug simulator build, Release simulator build, and package tests pass in run `38971260304`.
The former `ContentView.swift` contained 210,175 bytes and combined unrelated owners.
The root view now contains 45 lines.
Models, Bluetooth provisioning, the complete view model, shared style, feed cards, and screens have separate files.
All twelve moved source blocks retain their code. The extraction removes trailing whitespace.
The private optional-string helper remains with its feed-card callers.

The Swift package now compiles the extracted Foundation models and hardware profile.
Its new tests read the backend display, sports, profile, schedule, and schedule-status fixtures directly.
The Xcode source group includes the new application files automatically.
The package excludes UIKit services and views from its Foundation test target.

The extracted application passes Debug and Release simulator builds in run `38971899918`.
Both configurations pass the new package tests against backend fixtures.

## Mini text module

`rendering/text_primitives.cpp` owns drawing through an explicit `Adafruit_GFX` surface.
`rendering/text_layout.h` owns the fixed pane-text drawing loop.
`rendering/glyphs.h` owns the shared glyph index operation.
`rendering/presentation.inc` retains selection, dwell policy, and status-frame presentation.
Remove the former `rendering/primitives.inc` and its global text functions.
The module has no network, task, JSON-document, or matrix-global ownership.

The native check compares 3,054 character, clipping, position, and scale cases against the former drawing loop.
All cases retain identical pixels on the real Pi native runner.
The pinned PlatformIO build compiles the separate C++ module.
Static RAM changes from 77,036 to 77,020 bytes.
Application flash changes from 1,282,593 to 1,283,377 bytes.

The physical Mini runs `mini-1.3.11` after a verified USB flash.
The 90-second check collects 27 frames and 45 telemetry samples without capture errors.
All seven pane identities shared with the baseline retain their exact frame hashes.
Registration and data requests return 200. JSON failures remain zero. Panel refresh remains 200 Hz.
Timed visits range from 3,004.397 to 3,004.939 milliseconds.
The baseline range is 3,003.901 to 3,004.185 milliseconds.
Free-heap samples include startup and active TLS requests. They do not form a controlled memory benchmark.

## Transport extraction

The next extraction moves HTTP execution, shared TLS synchronization, HTTP diagnostics, and OTA into compiled modules.
The runtime applies responses through `network_results.inc` on the display task.
The iOS transport interface preserves existing request lifetime and polling owners.
Read [transport evidence and Wi-Fi options](network-modules-and-wifi-2026-10-16.md) for current checks and limits.

## Remaining Gate 6 work

The runtime still owns retained JSON, sprite coordination, connectivity, and initialization order.
The iOS view model still owns response policy and timers.
The app does not have a WebSocket transport today.
A future WebSocket change needs lifecycle and cancellation evidence before it replaces polling.

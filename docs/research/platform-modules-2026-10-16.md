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

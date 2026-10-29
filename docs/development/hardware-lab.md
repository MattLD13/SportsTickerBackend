# Virtual Hardware Lab

The lab runs the real Flask routes through Hypercorn ASGI. It also runs the Pi HTTP bootstrap, WebSocket stream client, poller, runtime, renderer, and 384x32 memory matrix sink.

Run it from the repository root:

```powershell
python tools\diagnostics\virtual_hardware_lab.py
```

The run uses a temporary SQLite database and an empty provider scheduler. It loads a deterministic source snapshot into the real backend projection. It captures online, disconnected, and recovered frames in `previews/virtual-hardware/`.

The report records HTTP routes, WebSocket messages, frame sizes, pixel hashes, and non-black pixels. The lab checks registration, snapshot bootstrap, delta delivery, disconnect handling, recovery, and score update rendering.

The report also compares 500 millisecond HTTP polling with the active WebSocket stream. It records local payload bytes, update latency, and projector reads over the same API.

Snapshot writes and API mutations wake the stream projector. A one-second check handles time-based rules and event expiry.

All network traffic uses loopback only. The lab injects one WebSocket transport loss in the Pi session. Image fetching stays disabled. Wi-Fi, reboot, and update commands stay disabled.

## Coverage

- Hypercorn ASGI lifespan, local HTTP routes, and device WebSocket serving.
- Real device registration and data routes.
- Backend snapshot projection and display content filtering.
- Poller state changes during success, transport loss, and recovery.
- Stream subprotocol negotiation, sequence delta application, and reconnect replay.
- Device stream metrics reach the ticker logger boundary.
- Real sports card rendering and connection-loss overlay composition.
- Matrix frame size, output pixels, and score-update invalidation.
- Local output evidence as PNG frames and JSON.

## Limits

The lab starts the backend API with an empty provider scheduler. It does not test live provider calls, credentials, or data freshness.

Efficiency values use loopback traffic and one sports fixture. They do not measure TLS overhead, provider delay, or production hardware load.

The lab binds a free loopback port directly. It does not test production bind settings or `create_production_application`.

The memory sink does not model RGBMatrix DMA timing, panel wiring, color calibration, power load, or electrical faults.

The ESP32 firmware still needs a separate native model or physical board for Wi-Fi, BLE, HUB75, OTA, and Mini protocol testing.

The iOS app and controller-to-backend flows need their own simulator or API harness. This lab does not emulate those devices.

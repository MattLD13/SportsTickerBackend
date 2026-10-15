# Mini sprite hardware checks

Date: 2026-10-15

## Release state

The backend sprite contract is deployed. Backend checksum correction: `e574533160b257f23f9d5ad7db5ea7c8fa8f2104`.
The USB-connected Mini runs local firmware `mini-1.3.0`. The firmware release remains unpublished until live network checks pass.

## Owners and removed paths

The backend owns public source selection, image preparation, immutable identity, refresh, and stored wire checksums.
The Mini owns validated LittleFS transactions, bounded eviction, RAM pixels, and serialized network work.
The shared image processor retains the Pi contained-image algorithms.
The firmware removes PNG/JPEG decoding, generated logo overrides, client URL selection, and URL cache records.

## Completed checks

- Python suite: 573 passed.
- Critical suite: 243 passed, 330 deselected.
- Ruff and scoped Mypy: passed.
- PlatformIO build and USB flash: passed. The uploader verified the flash hash.
- Serial boot: `Mini firmware: mini-1.3.0 sprite_protocol=1`.
- Cache mount: `Sprite cache ready files=0`.
- Encrypted BLE provisioning: `Encrypted provisioning result: OK`.
- Radio transition: `BLE host stopped`, followed by Wi-Fi association attempts without a reset.
- The saved home credential matches the working Pi credential. No credential appears in this report.
- Native C++ check on the real Pi: three Python wire vectors, every pixel, every mask value, and restart reuse passed.
- The native check also passed checksum rejection, truncated input, interrupted transactions, and bounded eviction.
- Two logos from a production Mini snapshot produced validated 705-byte sprites through the backend asset service.
- Local PNG previews use production snapshot data and the shared preparation path.
- The personal Pi service remained active during these checks. No screen takeover or replay ran.

## Network limit

A separate ESP32 Wi-Fi diagnostic found 20 access points on campus networks.
The Mini did not find its saved home network. The PC and personal Pi report the home network.
A reachable 2.4 GHz network is required for live sprite transfer checks.
The current Wi-Fi credentials remain in device NVS. The USB flash did not erase NVS.

## Provisioning findings

The first crash dump identified `nimble_host` during cross-core shutdown.
The shutdown task now uses the NimBLE host core and completes before the caller releases lifecycle state.
A second dump identified `wifi` during radio coexistence startup.
The SDK cannot restart either radio while the other radio owns coexistence state.
Provisioning now waits for a credential result read or client disconnect before it stops BLE and starts Wi-Fi.
The scheduler passes one timestamp into credential application. This removes unsigned elapsed-time underflow after the timer reset.

## Remaining hardware checks

- Connect the Mini to a reachable 2.4 GHz network.
- Confirm registration and the real V2 display payload.
- Confirm immutable sprite downloads, lengths, headers, masks, and checksums.
- Record free internal heap and largest free block during serialized TLS work.
- Reboot and confirm flash hits with no repeated downloads for cached logos.
- Check the physical panel for stable output and correct logos.

## Reproduction

```powershell
python -m pytest -q
python -m pytest -m critical -q
python -m ruff check sports_ticker ticker_core tools/mini_sprite_vectors.py
python -m mypy
python tools/mini_sprite_vectors.py --output .tmp/mini-sprites/vectors
```

Read [Mini Sprite V1](../contracts/mini-sprite-v1.md) for native C++ commands and the wire contract.

## Final USB image

Static RAM: 73,892 bytes. Application flash: 1,223,605 bytes.

SHA-256: `ee40c5aef007c47437f1559da8ae13079e91cd29f57a2c42758a5bd59902f1a9`.

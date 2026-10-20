# Mini sports sprite V1

The backend owns public source selection, image preparation, content identity, and source refresh.
The Mini owns validated flash storage, bounded eviction, and RAM-only rendering.

## Negotiation and reference

A Mini reports `metadata.mini_sprite_protocol: 1` during registration and heartbeat.
Its V2 sports records contain `data.away_logo_asset` and `data.home_logo_asset`.
The [reference schema](mini-sprite-asset.json) defines `pending`, `unavailable`, and `ready` states.
Only a ready reference supplies a binary URL and checksum.

The asset identity hashes source bytes, preparation method, pipeline version, dimensions, pixel format, mask order, and alpha policy.
The wire checksum is SHA-256 over the complete binary file.
Changed source bytes at the same URL receive a new identity after conditional source revalidation.
The default refresh interval is 900 seconds. A failed refresh retains the explicit last-good reference with `refreshing: true`.

## Binary layout

All multi-byte integers use little-endian order.

| Offset | Length | Value |
|---|---:|---|
| 0 | 4 | ASCII `MTS1` |
| 4 | 1 | Protocol version `1` |
| 5 | 1 | Preparation pipeline version `1` |
| 6 | 1 | Width `18` |
| 7 | 1 | Height `18` |
| 8 | 1 | Pixel format `1`: RGB565 little-endian |
| 9 | 1 | Mask format `1`: row-major bits, least-significant bit first |
| 10 | 2 | Pixel byte count `648` |
| 12 | 2 | Mask byte count `41` |
| 14 | 2 | Reserved, zero |
| 16 | 648 | RGB565 pixels in row-major order |
| 664 | 41 | Opacity mask. The final four unused bits are zero. |

Total length is exactly 705 bytes. Alpha blends source edges against black before RGB565 conversion.
The mask marks source pixels with nonzero prepared alpha.

## HTTP and storage

`GET /api/v2/assets/mini-sports/<asset_id>.mts` serves prepared public team art.
It accepts no upstream URL parameter. Invalid identities and missing or invalid files return 404.
Successful responses include content length, `X-Content-SHA256`, ETag, and immutable public caching headers.

The backend stores sources, sprites, and an atomic index outside the release tree.
The index retains each immutable sprite checksum until eviction. Reads compare stored bytes with that saved checksum.
Its default body cache limit is 8 MiB and 256 retained asset entries.
The Mini stores validated sprite files in `/sprites/`, with a limit of 128 completed files.
Each Mini write stages, closes, rereads, verifies, and renames the file before eviction.
The Mini evicts the oldest completed file and uses the identity as a deterministic time tie breaker.
One temporary file can exist during a write. Boot removes that temporary file.
Cache reads verify length, layout, and checksum before pixels enter RAM.
Network work shares the existing serialized Mini network owner.

## Rollout

Deploy the backend contract before flashing firmware that requires it.
Verify USB boot, sprite fetch, rendering, reboot cache reuse, corruption recovery, and TLS heap on the real Mini.
The Pi retains its RGBA assets and existing local outline decisions.

## Repeatable codec checks

Generate Python reference files from the repository root:

```powershell
python tools/mini/mini_sprite_vectors.py --output .tmp/mini-sprites/vectors
```

On Linux, compile the native check with the firmware header directory:

```sh
g++ -std=c++17 -O1 -Iesp32_hub75/src/mini/assets tests/native/mini_sprite_cache.cpp -ldl -o /tmp/mini-sprite-check
/tmp/mini-sprite-check .tmp/mini-sprites/vectors /tmp/mini-sprite-cache
```

The check loads the installed OpenSSL library. It verifies every decoded pixel and mask value against Python output.
It also verifies checksum rejection, truncated input, restart reuse, interrupted transactions, and bounded eviction.


## Stock cards

Mini stock records include `home_logo_asset` when the device advertises `mini_sprite_protocol: 1`.
The backend prepares company artwork from the stock provider through the same bounded sprite service.
The service accepts the approved Financial Modeling Prep image host.
The Mini scales the 18-pixel source sprite to the existing 16-pixel RAM logo size.
It preloads one logo per stock page and uses the shared page dwell setting.
Quote updates retain the visible stock when its identity stays in the selected list.
The stock card shows the logo, symbol, percentage change, and price.
Stock pages use the sports logo readiness check, initial progress screen, retry timing, and startup timeout.
After the startup timeout, an unavailable logo uses a symbol badge while downloads continue.

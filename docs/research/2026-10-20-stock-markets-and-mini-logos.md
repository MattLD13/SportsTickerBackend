# Smart markets, custom stock lists, and Mini logos

Date: 2026-10-20

## Behavior owners

The stock source owns quote refresh, smart selection, and the durable quote cache.
Display settings own one ordered custom stock list per ticker.
The V2 projection selects stock groups and enforces custom list order and membership.
The iOS Markets screen owns custom list editing and sharing symbols as text.
The Mini sprite service owns company image preparation and immutable asset references.
The Mini page scheduler and sprite worker own rotation, logo loading, cache residency, and retry timing.
The stock renderer reads prepared pixels without network access.

## Replaced paths

Smart categories replace their full fixed display lists with ranked selections.
Custom lists retain their saved order and can contain up to 30 symbols.
The stock provider settings key now includes custom symbols to isolate different ticker lists.
Mini stock pages replace the former text-only panel and first-quote-only display.
Stocks now use the sports logo readiness check, progress screen, retry timing, and startup timeout.

## Input and output evidence

The custom list input `nvda`, `BRK.B`, `NVDA`, `aapl` produces `NVDA`, `BRK.B`, `AAPL` in that order.
API checks preserve each ticker list across storage and reject invalid symbols without replacing the saved list.
Stock logo routes produce an 18-pixel immutable sprite with 705 bytes and a matching SHA-256 checksum.
The device uses the existing 16-pixel RAM logo cache.
Native renders use downloaded Apple, Nvidia, Tesla, and Berkshire company artwork with sample quote values.
The native stock check validates gains, losses, long values, missing logos, and 64-by-32 frame bounds.
The gallery rebuild changes only the three Mini stock examples. Six preview pixels remain unchanged.

## Release validation

Python correctness and scoped type checks pass.
The critical suite passes 780 tests, with ten skips and 351 deselected tests.
The Mini firmware builds for the production esp32s3 environment.
The full suite passes 1,131 tests, with ten skips. Hosted iOS builds remain a release gate.
Mini release version: `mini-1.3.37`.

The saved Mac address did not respond during release preparation.
The Mac checkout and installed phone app require separate confirmation after connection succeeds.

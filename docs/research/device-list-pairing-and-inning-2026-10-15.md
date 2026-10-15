# Device lists, Mini pairing, and baseball inning facts

Date: 2026-10-15

## Device list policy

`BackendApplication.visible_tickers` owns the list cutoff.
A device disappears from app, dashboard, and fleet lists after 30 days without a heartbeat.
The server records its own receipt time for each heartbeat. Client timestamps cannot extend or backdate device visibility.
A never-seen record uses its creation time until its first heartbeat.
The server retains settings, ownership, and controller tokens. A new heartbeat restores the device to lists.
An authorized controller receives an empty list when all its devices are inactive.
Invalid tokens still receive HTTP 403.

## Pairing correction

The Mini previously selected its displayed code from a nonempty cached Wi-Fi PIN.
That PIN cannot authorize an app through the server pairing route.
The Mini now uses its explicit setup state to select the code.
Wi-Fi setup displays `WIFI PIN` and `WIFI SETUP`.
Server pairing displays `APP PAIR` and `ADD TICKER`.
The transition clears the cached Wi-Fi PIN.
The app instructions distinguish these two codes.

`BackendApplication._device_pairing_record` owns server code renewal.
Registration and snapshot reads use the same serialized code lifecycle.
An unpaired device receives a fresh app code after expiry without a reboot.
A paired device receives no new code through snapshot polling.

## Baseball glyph contract

`sports_ticker/providers/sports_display.py` owns `baseball_inning_display`.
The V2 projection adds `data.baseball_inning` for baseball scoreboards.
The object contains `number`, `half`, and `phase`.
The contract distinguishes top, bottom, inning break, interruption, and inactive states.

Both main and Mini renderers read these facts. They do not parse inning state from status text.
The Mini arrow pixels come from the main ticker compact glyph definitions.
The native preview covers top innings, bottom extra innings, breaks, and delays.
The hockey preview now uses the actual timer-only power-play label instead of the invented `0:45 5v4` example.

## Deployment order

Deploy the backend contract before signaling Pi controller updates.
Mini OTA requests also wait for the backend deployment and runtime checks.
The UI firmware version is `mini-1.3.2`.

## Change notes

Owner: The backend owns visibility, app pairing codes, and inning facts. Mini runtime state selects its display code.
Former path: Remove client timestamp ownership, separate pairing refresh paths, cached-PIN selection, and client inning parsing.
Real input: Old heartbeat times, expired server codes, canonical baseball status, and explicit Mini Wi-Fi state.
Real output: Empty authorized lists, renewed usable app codes, inning arrows, and distinct Wi-Fi and app screens.

## Validation

The full suite passes 586 tests. The critical suite passes 256 tests.
Ruff, scoped Mypy, Python compilation, schema fixtures, and the ESP32 build pass.
Seventeen native Mini frames include the shared inning glyphs and both pairing states.
The USB upload verified its hash. Serial output confirms `mini-1.3.2` boots and initializes its cache.
The Mini still reports the saved `MattsWifi2.4` network as unavailable.
It returns to Wi-Fi setup after association attempts. No app pairing exchange can complete while it remains offline.

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
Initial home-network checks failed. Guest-network checks later established a working connection and app pairing.

## Wi-Fi radio investigation

The user confirms that the Mini is near the home router.
A separate Wi-Fi-only image reads the saved SSID and key length from NVS without changing credentials.
The saved SSID contains the exact bytes for `MattsWifi2.4`.
The Mini MAC is `58:8C:81:F1:7F:E4`. Its USB runtime port is `COM11`.
An active scan finds campus access points on channels 1, 6, and 11.
A passive scan on channel 5 succeeds but returns zero access points.
Direct association with the home router BSSID and channel also fails with reason `201`, `NO_AP_FOUND`.
The Pi concurrently reports the home router on channel 5 with signal strength 76 percent.
The Pi ticker service remains active.
These results do not establish the cause of the different radio observations.
The diagnostic image changes no server ownership, Pi settings, or stored Mini credentials.
The normal `mini-1.3.2` image replaces the diagnostic image after the radio checks.


## Guest network and secure transport

The Mini accepts an empty password for an open Wi-Fi network.
The encrypted provisioning envelope still requires string fields and enforces SSID and password byte limits.
The iOS setup form accepts the same limits and permits a blank password.
Physical BLE provisioning returned `OK` for `lehigh-guest` with an empty password.
The Mini obtained an address, registered, and fetched V2 data with HTTP 200.
The user confirmed successful app pairing with the displayed `APP PAIR` code.

All Mini HTTPS clients now use `configureTls` and the committed backend root store.
The former clients disabled certificate validation with `setInsecure`.
The compressed SDK trust bundle fails against the backend cross-signed certificate chain.
Standard PEM validation resolves the failure without adding an obsolete signing root.
A Wi-Fi-only hardware check accepts the backend and rejects wrong-host and self-signed certificates.
The ticker firmware then registers and fetches data with certificate validation enabled.

The physical `mini-1.3.3` development build reused two stored sprites after reboot.
A new sprite returned HTTP 200 with 705 bytes and passed validation.
Its observed free heap reached 98,668 bytes during TLS. Its largest free block measured 42,996 bytes.
The release target is `mini-1.3.4`. OTA reboot and acknowledgement require final release validation.
The full suite passes 589 tests. The critical suite passes 259 tests.

Owner: Mini connectivity owns credential validation. Shared TLS configuration owns every Mini HTTPS client.
Former path: Remove blank-password rejection and seven calls that disable server certificate checks.
Real input: Encrypted guest credentials, the production certificate chain, and persisted sprite files.
Real output: Successful pairing, verified HTTPS responses, cached sprites, and validated new sprite bytes.


## First physical OTA transfer

After pairing, the server delivered its previously queued `mini-1.2.8` command.
The secure `mini-1.3.3` development image downloaded and verified all 1,347,568 firmware bytes.
Serial output reported `Firmware update verified: mini-1.2.8` before the USB port reset.
The published older image booted, reconnected to guest Wi-Fi, registered, and fetched data with HTTP 200.
The new `mini-1.3.4` release will replace that older image through the normal deployment command.

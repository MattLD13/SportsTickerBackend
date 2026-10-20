# iOS request reliability and phone build

Date: 2026-10-19

## Behavior owners

`TickerRequestGate` owns request generation and server, ticker, and authorization identity checks.
`TickerViewModel` owns display reads, serialized settings writes, weather updates, and Spotify status.
`KeychainTickerCredentialStore` owns secure credential access through the existing service and account names.
`TickerHTTPClient.jsonData` validates request objects before Foundation writes JSON.
`BLEProvisioningCoordinator` owns the Bluetooth setup deadline and cancellation cleanup.

## Replaced behavior

Display reads previously applied responses without checking the current ticker or server.
Settings writes cancelled preceding writes and could report success after an HTTP or network failure.
Their completion handlers could release a newer edit lock or clear the entire device list after a rejected request.
Every settings save also forced score alerts on.

The new request gate rejects replaced requests and sessions.
Display reads allow one pending request and invalidate it when settings change.
Settings writes run serially and combine pending edits into the next write.
Only a confirmed successful final write refreshes data and copies shared team settings.
Failures release the edit lock and provide a visible error.
An unrelated settings save leaves the server's score-alert choice unchanged.

The team screen now uses the catalog's explicit team identifier.
The app no longer constructs an identifier from a display abbreviation.
The app no longer offers a debug toggle with no V2 action.

Bluetooth setup now stops after 60 seconds without completion.
It reports unavailable permissions and hardware support.
Closing setup cancels the local handoff and clears its password field.
Completion clears temporary Bluetooth credentials and callbacks before invoking the result callback.

## Existing Mac checkout

The deployment uses the existing `Desktop/SportsTickerBackend` checkout.
The coordinator saved its old branch, project-format changes, and Xcode window state before updating it to current main.
The old branch remains available. No old branch was merged.
The Mac retains its local Xcode formatting and window-state backup outside Git.

## Validation

The Swift package includes seven added regression tests for request identity, HTTP outcomes, and JSON number validation.
All 31 package tests passed in Debug and Release on the Mac.
Both simulator build configurations compiled.
The Python suite passed 1,086 tests, with ten skips.
The critical suite passed 738 tests, with ten skips and 348 deselected tests.

The additional simulator scenario uses the production `TickerViewModel` with controlled HTTP completion ordering.
It supplies in-memory test credentials through the same credential-store interface.
Production continues to use the real keychain by default.
This keeps test credentials outside the simulator keychain and prevents production network access.

The scenario checks delayed reads, delayed rejected writes, queued edits, schedule override preservation, and score-alert preservation.
It also checks failed-save recovery, cross-device isolation, and encoding failure cleanup.
The test harness retains its initial failed keychain setup attempt in local evidence.
The encoding-failure scenario found a Foundation exception for a non-finite numeric value.
The final encoder rejects invalid JSON objects before invoking Foundation and retains the error as a normal app message.

The signing certificate and provisioning profile already existed on the Mac.
Signing from its logged-in Terminal session provides the macOS key-access prompt required by that certificate.
The signed device app uses the existing `matt.TickerControl` bundle identifier.
Installation updates that app without an uninstall operation.

## Final evidence

The five conference-control simulator tests passed on iPhone 17 Pro Max with iOS 27.
The production-model scenario passed all 13 checks after the JSON validation fix.
The final signed Release build passed strict code-signature verification.
The device installer returned success, and the phone launched `matt.TickerControl` successfully.
The installed app reports version `3`, build `1`.
Its executable SHA-256 is `bfe1dc269ea45a3219141b01f8e90f9dcf25b976781894ea3e4a9c71a9da3cc0`.

Live public health, mode-catalog, and NFL-team-catalog requests returned HTTP 200 with a native app user agent.
The returned team records include explicit identifiers such as `nfl:ARI` and `nfl:ATL`.

Simulator checks use controlled data. Live Bluetooth provisioning and Spotify account authorization require their external devices and services.

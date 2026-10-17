# Mini connection and presence reliability

## Observed input

The user reported an offline label in the iOS app. Reopening the device list later showed online.
Read-only fleet diagnostic run `38996002310` reported online, with an 18.4-second heartbeat age.
The app uses a sixty-second presence threshold. Fleet health uses ninety seconds.
An offline label alone does not establish radio disconnection.

## Confirmed causes

A real Mini capture reproduced stale data while Wi-Fi remained connected with a strong signal.
Data age exceeded 317 seconds. Heartbeat age exceeded 333 seconds. The display continued rendering.
The pinned Arduino HTTPClient body loop waits indefinitely when the transport stays connected without delivering bytes.
Its configured read timeout does not bound that polling loop.
One stalled request therefore starved the single network worker and both data and separate heartbeat jobs.

The former reconnect path scanned synchronously and waited up to fifteen seconds on the display task.
After thirty disconnected seconds, it turned Wi-Fi off and entered BLE setup.
The scheduler then stopped saved-network retries. Temporary outages therefore had a recovery dead end.

The deployment recovery workflow compared every Git commit with the running backend version.
Documentation, iOS, and Mini commits therefore triggered unnecessary backend deployments.
The combined backend and Mini release also restarted the backend twice.

## Changed owners and removed paths

`DeadlineClient` bounds transport stream operations, including stalled HTTP body loops.
Normal transfers use a twenty-second budget. OTA downloads use five minutes.
SDK connection calls retain their own timeouts and can extend the nominal deadline.
Expired responses fail completeness checks. Later requests restore the normal budget.
`TlsTransport` retains the existing safe socket cleanup and certificate validation.

`WifiStation` owns association, radio event counters, and background recovery.
`StationRetry` owns the fifteen-second association deadline and one-to-thirty-second retry delay.
The former active scan and blocking reconnect loop are removed.
NVS records confirmed credentials after address acquisition. Confirmed networks retry indefinitely after an outage.
Normal outages do not enter BLE setup. New credentials can enter setup after thirty unsuccessful seconds.
Holding both board buttons for three seconds opens setup. Holding them again cancels setup and retries saved credentials.
USB `WIFISETUP` and `WIFIRETRY` invoke the same transitions.
BLE setup and Wi-Fi recovery remain separate lifecycle states.

The V2 POST device poll records presence and returns its snapshot in one request.
The Mini removes its separate heartbeat job. Existing GET snapshot reads remain read-only for Pi and app consumers.
Serial telemetry separates association state, data age, presence acknowledgement, and expired transfers.

`.github/deployment-paths.json` owns deployment target paths.
Both deployment filtering and recovery comparison read that scope.
`tools/deployment_scope.py` compares backend-changing revisions rather than unrelated Git HEAD changes.
The backend job owns the restart when both backend and Mini targets change.

## Validation

The full Python suite passes 625 tests. Touched Python modules pass compilation and Ruff checks.
A real temporary Git repository verifies recovery decisions across backend, root configuration, docs, Mini, iOS, and nested JSON changes.
The real Pi passes two hundred failed association attempts, recovery transitions, and timer rollover checks.
The transport test holds a fake stream connected without bytes. The production deadline wrapper closes it and rejects further operations.

Physical Mini candidate `mini-1.3.20` passes two forced forty-five-second association outages.
Fresh game data and presence resume 49.523 and 56.457 seconds after each diagnostic starts.
These totals include the full forced outage. Recovery takes approximately five and eleven additional seconds.
Neither outage enters BLE setup. Stored credentials and app pairing remain intact.
The candidate uses 77,228 bytes of static RAM and 1,297,905 bytes of application flash.
A forced one-millisecond request budget records a timeout. A later normal poll succeeds.
Explicit BLE setup opens and returns to the saved network without a panic.

An earlier unpublished candidate mixed automatic BLE setup with normal Wi-Fi recovery.
Its exact-symbol crash dump identified an abort in `coex_core_enable` during driver startup.
The final lifecycle separates these operations. Failed candidates were not published.

Local evidence lives under `previews/wifi-reliability/`. Generated logs and binaries are not source files.
The association diagnostic tests link recovery. It does not control the campus access point or its internet service.

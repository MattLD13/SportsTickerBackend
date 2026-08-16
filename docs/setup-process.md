# Ticker setup process

This diagram covers factory testing, shipment, customer setup, and a second controller joining an existing ticker.

```mermaid
flowchart TD
    A[Factory: flash firmware] --> B[test.py color cycle]
    B --> C[Register ticker with V2 backend]
    C --> D[Print identity label from labels/ticker-identity-template.svg]
    D --> E[Pack ticker and quick-start card]
    E --> F[Customer unboxes ticker]
    F --> G{Ticker has Wi-Fi?}
    G -->|Yes| H[App opens dashboard]
    G -->|No| I[Ticker shows Open Ticker Control App and six-digit PIN]
    I --> J[App full-screen setup gate]
    J --> K{Use current Wi-Fi?}
    K -->|Yes| L[iOS reads current SSID]
    K -->|No| M[Customer enters another SSID]
    L --> N[App scans for SportsTicker Setup over BLE]
    M --> N
    N --> O[App encrypts SSID and password with code plus ticker challenge]
    O --> P[Ticker saves network and reboots]
    P --> Q[Ticker registers and shows pair code]
    Q --> R[App exchanges pair code for controller token]
    R --> H
    H --> S{Another person needs access?}
    S -->|Yes| T[Owner issues fresh pair code]
    T --> U[Second person uses Connect existing ticker]
    U --> R
    S -->|No| V[Normal operation and heartbeat telemetry]
```

## Security boundaries

- The six-digit code gates the temporary setup session. The app derives a per-session BLE encryption key from the code and ticker challenge.
- The setup session expires after 15 minutes and limits failed submissions.
- Pair codes expire after 10 minutes and become single-use controller tokens.
- The permanent label contains identity fields only. It does not contain the temporary Wi-Fi password.
- Production setup uses authenticated BLE GATT. The hotspot portal remains an explicit bench fallback with `TICKER_SETUP_TRANSPORT=hotspot`.
- Production backend traffic uses TLS and deployment-authorized fleet health access.

The Pi runtime uses BLE by default. Set `TICKER_SETUP_TRANSPORT=hotspot` only for controlled bench testing when a phone cannot use Bluetooth. Run `python test.py --sink hardware --report C:\ticker\diagnostic.json` before shipment.

The forced test command writes a one-shot marker. The running service consumes it on its first Wi-Fi check, so a reboot returns to normal Wi-Fi detection instead of restarting the test state.

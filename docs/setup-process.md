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
    L --> N[App joins SportsTicker_Setup]
    M --> N
    N --> O[App sends SSID, password, and code over local HTTPS]
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

- The six-digit code gates the temporary setup session. The app derives the hotspot password internally, so the ticker does not display it.
- The setup session expires after 15 minutes and limits failed submissions.
- Pair codes expire after 10 minutes and become single-use controller tokens.
- The permanent label contains identity fields only. It does not contain the temporary Wi-Fi password.
- The local setup portal runs over HTTPS on the temporary ticker hotspot. The ticker creates a short-lived certificate for the setup session.
- Production backend traffic uses TLS and deployment-authorized fleet health access.

Run `python test.py --sink hardware --report C:\ticker\diagnostic.json` before shipment. Run the hotspot option only during controlled bench testing.

# Testing

Run the focused V2 suite from the repository root:

```powershell
python -m pytest -q
```

The tests live in `tests/rewrite/`. They use temporary SQLite files, injected provider ports, and memory frame sinks. They do not start the production scheduler or require panel hardware.

Use the renderer for display verification:

```powershell
python tools\render_rewrite.py --snapshot tests\rewrite\debug\v2_render_snapshot.json --mode sports --item-id mlb-live --pinned --no-prefetch --output previews\mlb.png
```

Run the controller contract harness:

```powershell
python tools\v2_control_harness.py --self-test
```

Run the Pi manufacturing diagnostic with a persistent report:

```powershell
python test.py --sink hardware --report C:\ticker\diagnostic.json
```

Run the destructive hotspot and portal check only on a controlled bench:

```powershell
python test.py --sink hardware --wifi-setup --portal --report C:\ticker\wifi-diagnostic.json
```

Force the running ticker service into its real Wi-Fi setup mode without changing saved credentials:

```bash
python3 test.py --force-wifi-setup
```

Keep the command running while the app joins `SportsTicker_Setup` and submits the network. Press `Ctrl+C` after setup so the command removes its fifteen-minute test marker.

The diagnostic flashes every panel color, checks the backend payload, probes internet access, scans NetworkManager, validates the setup portal, and records bounded JSON results. It requests no reboot unless `--reboot` is supplied.

The harness checks sports filters, pin, unpin, strip replacement, and live delay without an iOS build.

For every code change, keep one focused boundary test. If pixels change, save and inspect a real 384x32 frame. Do not keep tests for deleted V1 routes or controller code.

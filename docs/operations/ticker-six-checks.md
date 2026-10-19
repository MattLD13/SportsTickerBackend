# Real Pi Smoke Check

Run this check from a workstation that can reach the backend and the Pi over SSH.

```powershell
python tools/diagnostics/live_ticker_hardware_smoke.py `
  --ticker-id 722c59f4-fce3-4735-b072-faaa2f579a0a `
  --ssh-target mld@ticker2.local `
  --ssh-key "$env:USERPROFILE\.ssh\ticker2_codex"
```

The check posts a unique news test with a 60-second expiry, then reads the Pi performance log over SSH.
It passes after the Pi accepts the payload, advances its WebSocket sequence, and records a 384x32 display frame.
After expiry, the check confirms that the server removes the event and the Pi records the cleared payload.

Run the fifteen-game matrix load check from the workstation:

```powershell
python tools/diagnostics/live_pi_scoreboard_stress.py `
  --ssh-target mld@ticker2.local `
  --ssh-key "$env:USERPROFILE\.ssh\ticker2_codex" `
  --duration-seconds 60
```

The load check pauses the controller, shows fifteen synthetic live games on the physical matrix, measures score updates, then restores the controller.
It saves one rendered frame and a telemetry report under `.tmp/real-pi-scoreboard-stress/`.

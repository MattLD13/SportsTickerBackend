# ticker_controller/modes Agent Guide

Mode-specific drawing code for the LED ticker.

## Practices
- Keep drawing functions deterministic and cheap. Cache composed strips when rebuilding every frame would stutter.
- Use exact pixel coordinates and render real previews after changes.
- Use helper functions for repeated tiny icons/text layout.
- Avoid adding large image assets when a small generated pixel treatment works.

## Racing
- `indycar.py` contains the shared racing card layout.
- `f1.py` adapts F1 data into the racing layout and draws generated cars from team colors.

## Score Alerts
- `score_alert.py` draws the full-screen takeover for a followed team's scoring play.
- It preempts whatever is on screen, so it is driven straight from `render_loop`, not from `draw_single_game`.
- Whether an alert fires at all is the backend's call — it only sends them to a board in a sports mode. Do not add a second mode check here.
- The backend supplies the headline text; this module only lays it out.

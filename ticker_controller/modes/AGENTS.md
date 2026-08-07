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
- `score_alert.py` draws the full-screen takeover for a scoring play by a followed team.
- An alert replaces all other content. `render_loop` calls it directly, not `draw_single_game`.
- The backend decides when an alert fires. It sends alerts only to a ticker in a sports mode. Do not add a second mode check here.
- The backend supplies the headline text. This module only draws it.

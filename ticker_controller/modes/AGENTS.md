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

## News Banner
- `news_banner.py` draws the half-width banner for a trade or a stock headline.
- It rides on the scroll. `render_loop` lays it over each ordinary frame, so the strip keeps moving in the half beside it.
- Do not make it block the loop the way a score alert does. Losing the scroll is the thing this design avoids.
- The backend decides what appears and in which mode. This module only draws it.

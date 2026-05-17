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

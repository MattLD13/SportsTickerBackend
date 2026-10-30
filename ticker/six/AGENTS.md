# Ticker Six

Keep rendering free of file access, network access, and scheduling policy.
Use the shared backend projection for sports state and lifecycle facts.
`ui/` owns the drawing. `ui/sports/` owns the sports cards. `ui/cards/` holds one card for each other content family.
Each card owns its `visual_key`. The key changes exactly when the drawn image can change.
If pixels change, run `python tools/rendering/six_golden.py check`. Accept a change on purpose with `accept` only after you inspect the frames.
`platform/assets.py` owns durable image storage. `assets/` owns planning and memory reads.
Keep panel geometry at `384x32`.
If pixels change, render with `tools/rendering/render_frame.py` and inspect the PNG.
Keep generated images and bytecode outside Git.
Pi deployments use immutable releases. Runtime data stays outside the release.

# Ticker Six

Keep rendering free of file access, network access, and scheduling policy.
Use the shared backend projection for sports state and lifecycle facts.
`features/sports/` owns sports panes. Each content family owns its renderer under `features/`.
`platform/assets.py` owns durable image storage. `assets/` owns planning and memory reads.
Keep panel geometry at `384x32`.
If pixels change, render with `tools/rendering/render_frame.py` and inspect the PNG.
Keep generated images and bytecode outside Git.
Pi deployments use immutable releases. Runtime data stays outside the release.

# SportsTickerBackend Agent Guide

Read this file in full before you change code. Read `AGENTS.md` in full too.
The rules apply to all changes, including one-line bug fixes.

## Build Properly

- Find the cause before you edit. Trace input, durable state, API output, client state, and rendered frame.
- Give each fact one owner. Put shared display facts in the version two domain projection.
- Extend a stable contract when more than one consumer needs a fact. Do not copy business rules across layers.
- Replace a faulty design. Do not add compatibility branches, hidden fallbacks, or special cases.
- Remove replaced code and tests in the same change. Do not keep stale imports, fixtures, routes, jobs, or docs.
- Keep provider work, persistence, API projection, scheduling, and rendering separate.
- Do not infer domain state from rendered strings in a client. The backend contract must state it directly.
- Make one focused validation across the changed boundary. Render a real 384x32 frame after display changes.
- Remove obsolete test plumbing when it fails. Do not add dummy modules to preserve removed code.

Before a commit, state the owner, the removed path, and the evidence for the new path.

## Project Rules

Read and follow the complete project guide in `AGENTS.md`. It defines architecture, validation, generated artifacts, and writing rules.

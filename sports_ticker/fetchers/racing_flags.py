"""
Shared flag constants for all racing series.

Usage in any new racing fetcher:
    from .racing_flags import LIVE_FLAGS, CAUTION_FLAGS, normalize_flag

    flag = normalize_flag(api_response.get('flagStatus'))
    state   = 'in' if flag in LIVE_FLAGS else ...
    caution = flag in CAUTION_FLAGS
"""

# ---------------------------------------------------------------------------
# All flag values that indicate a session is actively running.
# Import into a fetcher to decide state='in'.
# ---------------------------------------------------------------------------
LIVE_FLAGS: frozenset[str] = frozenset({
    # ── Green ──────────────────────────────────────────────────────────────
    'GREEN', 'CLEAR', 'ROLLING START', 'FORMATION LAP',

    # ── Yellow (any full-course / local caution) ───────────────────────────
    'YELLOW', 'DOUBLE YELLOW', 'CAUTION', 'DEBRIS',
    'FCY', 'FULL COURSE YELLOW', 'LOCAL YELLOW',
    'SLOW ZONE',                        # WEC local slow zone
    'CODE 60', 'CODE60',                # Nürburgring / VLN sector slow

    # ── Safety Car / Virtual / Pace Car ───────────────────────────────────
    'SAFETY CAR', 'SC',
    'VSC', 'VIRTUAL SAFETY CAR',
    'VSC ENDING', 'SC ENDING',
    'PACE CAR', 'PACE',                 # NASCAR / IMSA alias

    # ── Neutralised (rally-cross, Pikes Peak, etc.) ───────────────────────
    'NEUTRALISED', 'NEUTRALIZED',

    # ── Red (session is paused but still "in") ────────────────────────────
    'RED', 'RED FLAG',

    # ── White / Checkered ─────────────────────────────────────────────────
    'WHITE',        # final lap
    'CHECKERED',
})

# ---------------------------------------------------------------------------
# Flag values that should set caution=True on the game object.
# Everything except green / white / checkered / blue / black.
# ---------------------------------------------------------------------------
CAUTION_FLAGS: frozenset[str] = frozenset({
    # Yellow family
    'YELLOW', 'DOUBLE YELLOW', 'CAUTION', 'DEBRIS',
    'FCY', 'FULL COURSE YELLOW', 'LOCAL YELLOW',
    'SLOW ZONE',
    'CODE 60', 'CODE60',

    # Safety car family
    'SAFETY CAR', 'SC',
    'VSC', 'VIRTUAL SAFETY CAR',
    'VSC ENDING', 'SC ENDING',
    'PACE CAR', 'PACE',

    # Neutralised
    'NEUTRALISED', 'NEUTRALIZED',

    # Red
    'RED', 'RED FLAG',
})


def normalize_flag(raw: str) -> str:
    """Strip and upper-case a raw flag string from any racing API."""
    return str(raw or '').strip().upper()

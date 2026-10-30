"""Classify racing sessions consistently for sources and display clients."""

def racing_timed_session(session: object) -> bool:
    """Classify practice, qualifying, and time-trial sessions from source labels."""
    name = str(session or "").lower()
    return any(
        keyword in name
        for keyword in (
            "qual",
            "fast",
            "top 12",
            "last chance",
            "hyperpole",
            "pole",
            "shootout",
            "prac",
            "fp",
            "warm",
            "shakedown",
            "test",
            "time trial",
        )
    )

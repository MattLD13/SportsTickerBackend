"""Classify racing sessions consistently for sources and display clients."""

def racing_timed_session(session: object) -> bool:
    """Classify practice, qualifying, and time-trial sessions from source labels."""
    name = str(session or "").lower()
    if name.strip() in {"q", "q1", "q2", "q3", "sq", "sq1", "sq2", "sq3"}:
        return True
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

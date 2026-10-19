"""Read a private device credential for local hardware inspection tools."""
from pathlib import Path
import os
import re


def device_headers(token_file: Path | str | None = None) -> dict[str, str]:
    selected = token_file or os.environ.get("TICKER_DEVICE_TOKEN_FILE")
    if not selected:
        return {}
    token = Path(selected).expanduser().read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("The selected device credential is invalid")
    return {"X-Device-Token": token}

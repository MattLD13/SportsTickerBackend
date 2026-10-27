"""Keep a durable device secret outside immutable release directories."""
from __future__ import annotations
import os
import re
import secrets
from pathlib import Path


def load_device_token(path: Path) -> str:
    """Create a private secret once and reject corrupted durable credentials."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(secrets.token_hex(32) + "\n")
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    token = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("The durable device credential is invalid")
    os.chmod(path, 0o600)
    return token

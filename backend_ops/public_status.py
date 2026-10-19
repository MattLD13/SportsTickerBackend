"""Expose deployment identities and quarantine decisions without private evidence."""
from pathlib import Path

from .manager import read


def summary(data_directory):
    state = read(Path(data_directory) / "backend-control/state.json")
    return {"processed_revision": state.get("processed_revision"),
            "pending": bool(state.get("pending")),
            "components": {name: {key: record.get(key) for key in ("active", "previous", "quarantined")}
                           for name, record in state.get("components", {}).items()}}

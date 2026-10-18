"""Keep update results outside release folders until the server accepts them."""
from __future__ import annotations
import json
import os
from pathlib import Path


class UpdateJournal:
    def __init__(self, directory: Path):
        self.path = Path(directory) / "update-result.json"
        self.notice_path = Path(directory) / "update-notice-shown.json"
        self.ack_path = Path(directory) / "update-result-ack.json"

    @staticmethod
    def _read(path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except FileNotFoundError:
            return None

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + "." + str(os.getpid()))
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def load(self):
        return self._read(self.path)

    def save(self, value):
        self._write(self.path, value)

    def notice_pending(self, receipt):
        """Keep display acknowledgement separate from server delivery."""
        return receipt.get("status") in {"rolled_back", "download_failed"} and self._read(self.notice_path) != {
            "id": receipt["id"], "status": receipt["status"],
        }

    def mark_notice_shown(self, receipt):
        """Acknowledge a failure only after the display presents its frame."""
        self._write(self.notice_path, {"id": receipt["id"], "status": receipt["status"]})

    def flush(self, client, ticker_id):
        receipt = self.load()
        if receipt is None or receipt.get("status") not in {"started", "installed", "rolled_back", "download_failed"}:
            return None
        identity = {key: receipt[key] for key in ("id", "status")}
        if self._read(self.ack_path) == identity:
            return None
        report = {key: receipt[key] for key in ("id", "version", "status", "running_version", "reason")}
        result = client.report_update(ticker_id, report)
        if result.get("accepted"):
            self._write(self.ack_path, identity)
        return result

"""Read public racing snapshots through their published socket protocols."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any


def open_timing_socket(url: str, *, timeout: float):
    """Open the same public connection used by the official timing page."""
    import websocket

    return websocket.create_connection(url, timeout=timeout, origin="https://" + url.split("/")[2])


class AlkamelSnapshot:
    """Collect DDP documents until the requested public subscription is ready."""

    def __init__(self, socket_factory: Callable = open_timing_socket, *, timeout: float = 10):
        self.socket = socket_factory("wss://livetiming.alkamelsystems.com/websocket", timeout=timeout)
        self.socket.send(json.dumps({"msg": "connect", "version": "1", "support": ["1"]}))
        self.documents: dict[str, dict[str, dict[str, Any]]] = {}
        self.serial = 0
        self.timeout = timeout

    def read(self, subscriptions: list[tuple[str, list]]) -> dict[str, list[dict[str, Any]]]:
        """Read complete initial documents without waiting for a later race update."""
        waiting = set()
        for name, params in subscriptions:
            self.serial += 1
            identifier = str(self.serial)
            waiting.add(identifier)
            self.socket.send(json.dumps({"msg": "sub", "id": identifier, "name": name, "params": params}))
        deadline = time.monotonic() + self.timeout
        while waiting and time.monotonic() < deadline:
            message = json.loads(self.socket.recv())
            kind = message.get("msg")
            if kind == "ping":
                self.socket.send(json.dumps({"msg": "pong", **({"id": message["id"]} if "id" in message else {})}))
            elif kind == "ready":
                waiting.difference_update(message.get("subs", ()))
            elif kind == "nosub":
                raise ValueError("Official timing subscription failed: " + str(message.get("error")))
            elif kind in {"added", "changed"}:
                document = self.documents.setdefault(message["collection"], {}).setdefault(message["id"], {})
                document.update(message.get("fields", {}))
                for key in message.get("cleared", ()):
                    document.pop(key, None)
            elif kind == "removed":
                self.documents.get(message["collection"], {}).pop(message["id"], None)
        if waiting:
            raise TimeoutError("Official timing snapshot did not become ready")
        return {name: list(documents.values()) for name, documents in self.documents.items()}

    def close(self) -> None:
        self.socket.close()


def read_nbr24_snapshot(socket_factory: Callable = open_timing_socket, *, timeout: float = 10) -> dict[str, Any]:
    """Read the results and track state for the organizer's event 50 channel."""
    connection = socket_factory("wss://livetiming.azurewebsites.net/", timeout=timeout)
    try:
        connection.send(json.dumps({"eventId": 50, "eventPid": [0, 4], "clientLocalTime": int(time.time() * 1000)}))
        deadline = time.monotonic() + timeout
        result: dict[str, Any] = {}
        while time.monotonic() < deadline:
            message = json.loads(connection.recv())
            pid = str(message.get("PID", ""))
            if pid == "LTS_NOT_FOUND":
                return {}
            if pid == "LTS_TIMESYNC":
                result["server_time"] = message.get("serverLocalTime")
            elif pid == "0":
                result["results"] = message
            elif pid == "4":
                result["track"] = message
            if "results" in result and "track" in result:
                return result
        raise TimeoutError("Nürburgring timing did not provide a complete snapshot")
    finally:
        connection.close()

"""Continuously exercise the mini ticker BLE Wi-Fi provisioning flow."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from threading import Event, Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from serial import Serial
from serial.tools import list_ports


SERVICE_UUID = "8F8B0001-6E2A-4D8A-9F31-8D4B77F0B001"
CHALLENGE_UUID = "8F8B0002-6E2A-4D8A-9F31-8D4B77F0B001"
CREDENTIALS_UUID = "8F8B0003-6E2A-4D8A-9F31-8D4B77F0B001"
RESULT_UUID = "8F8B0004-6E2A-4D8A-9F31-8D4B77F0B001"
PAIRING_UUID = "8F8B0005-6E2A-4D8A-9F31-8D4B77F0B001"
PROTOCOL_INFO = b"SportsTicker BLE Wi-Fi v1"
PIN_PATTERN = re.compile(r"BLE pairing PIN:\s*(\d{6})")
APP_PORTS = {(0x303A, 0x1001), (0x239A, 0x8125)}


class PairerState:
    def __init__(self) -> None:
        self.lock = Lock()
        self.setup_code: str | None = None
        self.last_pin_at = 0.0

    def update_pin(self, value: str) -> None:
        with self.lock:
            self.setup_code = value
            self.last_pin_at = time.monotonic()

    def read_pin(self) -> tuple[str | None, float]:
        with self.lock:
            return self.setup_code, self.last_pin_at


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(path, encoding="utf-8")],
    )


def find_serial_port() -> str | None:
    ports = list(list_ports.comports())
    preferred = [
        port.device
        for port in ports
        if (port.vid, port.pid) in APP_PORTS
    ]
    return preferred[0] if preferred else (ports[0].device if ports else None)


def serial_reader(stop: Event, state: PairerState) -> None:
    while not stop.is_set():
        port = find_serial_port()
        if port is None:
            time.sleep(2)
            continue
        try:
            logging.info("serial open port=%s", port)
            with Serial(port, 115200, timeout=1) as serial:
                while not stop.is_set():
                    raw = serial.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    logging.info("ticker %s", line)
                    match = PIN_PATTERN.search(line)
                    if match:
                        state.update_pin(match.group(1))
        except Exception as error:  # The USB CDC port disappears during reset.
            logging.warning("serial disconnected: %s", error)
            time.sleep(1)


def encrypt_credentials(setup_code: str, ssid: str, password: str, challenge: bytes) -> list[bytes]:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=challenge,
        info=PROTOCOL_INFO,
    ).derive(setup_code.encode("utf-8"))
    nonce = os.urandom(12)
    plaintext = json.dumps({"ssid": ssid, "password": password}, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, challenge)
    envelope = {
        "v": 1,
        "challenge": challenge.hex(),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    payload = base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8")).decode("ascii")
    width = 120
    parts = [payload[index : index + width] for index in range(0, len(payload), width)]
    return [f"{index}/{len(parts)}:{part}".encode("utf-8") for index, part in enumerate(parts)]


def exchange_pairing_code(backend_url: str, pairing_code: str) -> dict[str, Any]:
    url = backend_url.rstrip("/") + "/api/v2/pairings/exchange"
    body = json.dumps({"pairing_code": pairing_code}).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"pairing exchange HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"pairing exchange network error: {error.reason}") from error


async def wait_for_backend_code(client: BleakClient, characteristic, initial: str, timeout: float) -> str | None:
    if initial and initial != "NONE":
        return initial
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = (await client.read_gatt_char(characteristic)).decode("utf-8", errors="replace").strip()
        if value and value != "NONE":
            return value
        await asyncio.sleep(1)
    return None


async def pair_once(args: argparse.Namespace, state: PairerState) -> bool:
    logging.info("scanning for MiniTicker BLE service")
    discovered = await BleakScanner.discover(timeout=args.scan_seconds, return_adv=True)
    devices = []
    for device, advertisement in discovered.values():
        service_uuids = {str(value).upper() for value in advertisement.service_uuids}
        if SERVICE_UUID.upper() in service_uuids or (device.name or "").lower() == "miniticker setup":
            devices.append(device)
    if not devices:
        logging.info("no ticker found advertisements=%d", len(discovered))
        return False

    device = devices[0]
    logging.info("connecting address=%s name=%s", device.address, device.name)
    async with BleakClient(device, timeout=20) as client:
        service_chars = []
        for service in client.services:
            if str(service.uuid).upper() != SERVICE_UUID.upper():
                continue
            service_chars.extend(service.characteristics)
        def characteristic(uuid: str, required: str):
            matches = [item for item in service_chars if str(item.uuid).upper() == uuid.upper() and required in item.properties]
            if not matches:
                raise RuntimeError(f"BLE characteristic unavailable uuid={uuid} property={required}")
            return matches[0]
        challenge_characteristic = characteristic(CHALLENGE_UUID, "read")
        credentials_characteristic = characteristic(CREDENTIALS_UUID, "write")
        result_characteristic = characteristic(RESULT_UUID, "read")
        pairing_characteristic = characteristic(PAIRING_UUID, "read")
        challenge = bytes(await client.read_gatt_char(challenge_characteristic))
        initial_pairing_code = (await client.read_gatt_char(pairing_characteristic)).decode("utf-8", errors="replace").strip()
        setup_code, pin_time = state.read_pin()
        if args.setup_code:
            setup_code = args.setup_code
        if not setup_code or not re.fullmatch(r"\d{6}", setup_code):
            logging.error("BLE is available, but no six-digit setup PIN is in the serial log")
            return False
        logging.info("sending encrypted Wi-Fi credentials setup_pin_age=%.1fs", time.monotonic() - pin_time)
        for packet in encrypt_credentials(setup_code, args.ssid, args.password, challenge):
            await client.write_gatt_char(credentials_characteristic, packet, response=True)
        result = (await client.read_gatt_char(result_characteristic)).decode("utf-8", errors="replace").strip()
        logging.info("ticker credential result=%s", result)
        if result != "OK":
            return False

        pairing_code = await wait_for_backend_code(client, pairing_characteristic, initial_pairing_code, args.backend_wait_seconds)
        if not pairing_code:
            logging.warning("Wi-Fi accepted, but no backend pairing code arrived")
            return True
        logging.info("exchanging backend pairing code")
        response = await asyncio.to_thread(exchange_pairing_code, args.backend_url, pairing_code)
        logging.info("pairing exchange succeeded ticker_id=%s", response.get("ticker_id", ""))
        return True


async def run(args: argparse.Namespace) -> None:
    state = PairerState()
    stop = Event()
    serial_task = asyncio.create_task(asyncio.to_thread(serial_reader, stop, state))
    started = time.monotonic()
    try:
        while not args.duration or time.monotonic() - started < args.duration:
            try:
                await pair_once(args, state)
            except Exception as error:
                logging.exception("pair attempt failed: %s", error)
            await asyncio.sleep(args.retry_seconds)
    finally:
        stop.set()
        await asyncio.wait_for(serial_task, timeout=3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssid", default=os.getenv("MINI_TICKER_WIFI_SSID", "MattsWifi2.4"))
    parser.add_argument("--password", default=os.getenv("MINI_TICKER_WIFI_PASSWORD"), required=False)
    parser.add_argument("--backend-url", default="https://ticker.mattdicks.org")
    parser.add_argument("--setup-code", help="Use a fixed setup PIN instead of the serial log")
    parser.add_argument("--scan-seconds", type=float, default=8)
    parser.add_argument("--backend-wait-seconds", type=float, default=90)
    parser.add_argument("--retry-seconds", type=float, default=3)
    parser.add_argument("--duration", type=float, default=0, help="Stop after this many seconds, or run forever")
    parser.add_argument("--log-file", type=Path, default=Path("logs/mini_ticker_test_pairer.log"))
    args = parser.parse_args()
    if not args.password:
        parser.error("set --password or MINI_TICKER_WIFI_PASSWORD")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    configure_logging(arguments.log_file)
    logging.info("mini ticker test pairer started ssid=%s backend=%s", arguments.ssid, arguments.backend_url)
    try:
        asyncio.run(run(arguments))
    except KeyboardInterrupt:
        logging.info("stopped")

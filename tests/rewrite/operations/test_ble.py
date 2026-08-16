from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from ticker_core.platform.ble import _BleSessionState, derive_ble_key, decrypt_credentials


def make_envelope(code: str, challenge: bytes, ssid: str, password: str) -> bytes:
    nonce = bytes(range(12))
    plaintext = json.dumps({"ssid": ssid, "password": password}, separators=(",", ":")).encode()
    encrypted = AESGCM(derive_ble_key(code, challenge)).encrypt(nonce, plaintext, challenge)
    return json.dumps(
        {
            "v": 1,
            "challenge": challenge.hex(),
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(encrypted).decode(),
        },
        separators=(",", ":"),
    ).encode()


def test_ble_envelope_authenticates_and_decrypts_wifi_credentials() -> None:
    challenge = bytes.fromhex("00112233445566778899aabbccddeeff")
    envelope = make_envelope("123456", challenge, "Home", "secret")

    assert decrypt_credentials(envelope, "123456", challenge) == ("Home", "secret")

    try:
        decrypt_credentials(envelope, "654321", challenge)
    except InvalidTag:
        pass
    else:
        raise AssertionError("wrong setup code must not decrypt Wi-Fi credentials")


def test_ble_session_reassembles_chunks_and_calls_callback() -> None:
    challenge = bytes.fromhex("00112233445566778899aabbccddeeff")
    received: list[tuple[str, str]] = []
    state = _BleSessionState("123456", challenge, lambda ssid, password: received.append((ssid, password)), __import__("threading").Event())
    encoded = base64.b64encode(make_envelope("123456", challenge, "Home", "secret")).decode()
    midpoint = len(encoded) // 2

    state.write(f"1/2:{encoded[midpoint:]}".encode())
    state.write(f"0/2:{encoded[:midpoint]}".encode())

    assert state.result == b"OK"
    assert state.completed is True
    # Callback execution is intentionally detached from the D-Bus write handler.
    import time
    for _ in range(20):
        if received:
            break
        time.sleep(0.01)
    assert received == [("Home", "secret")]

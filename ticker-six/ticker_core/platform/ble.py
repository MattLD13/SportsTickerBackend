"""Bluetooth Low Energy Wi-Fi provisioning for Raspberry Pi tickers.

The Pi advertises a short-lived GATT service. The app reads a random challenge,
reads the backend pairing code, and writes an AES-GCM envelope derived from the
six-digit setup code. Wi-Fi credentials never travel as plaintext.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


BLE_SERVICE_UUID = "8f8b0001-6e2a-4d8a-9f31-8d4b77f0b001"
BLE_CHALLENGE_UUID = "8f8b0002-6e2a-4d8a-9f31-8d4b77f0b001"
BLE_CREDENTIALS_UUID = "8f8b0003-6e2a-4d8a-9f31-8d4b77f0b001"
BLE_RESULT_UUID = "8f8b0004-6e2a-4d8a-9f31-8d4b77f0b001"
BLE_PAIRING_UUID = "8f8b0005-6e2a-4d8a-9f31-8d4b77f0b001"
BLE_LOCAL_NAME = "SportsTicker Setup"
BLE_PROTOCOL_INFO = b"SportsTicker BLE Wi-Fi v1"


def derive_ble_key(setup_code: str, challenge: bytes) -> bytes:
    """Derive the per-session AES key from the displayed setup code and challenge."""

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=challenge,
        info=BLE_PROTOCOL_INFO,
    ).derive(setup_code.encode("ascii"))


def decrypt_credentials(payload: bytes, setup_code: str, challenge: bytes) -> tuple[str, str]:
    """Authenticate and decrypt one app Wi-Fi envelope."""

    envelope = json.loads(payload.decode("utf-8"))
    if envelope.get("v") != 1 or envelope.get("challenge") != challenge.hex():
        raise ValueError("BLE setup challenge is invalid")
    nonce = base64.b64decode(str(envelope["nonce"]))
    ciphertext = base64.b64decode(str(envelope["ciphertext"]))
    plaintext = AESGCM(derive_ble_key(setup_code, challenge)).decrypt(nonce, ciphertext, challenge)
    values = json.loads(plaintext.decode("utf-8"))
    ssid = str(values.get("ssid") or "").strip()
    password = str(values.get("password") or "")
    if not ssid or not password:
        raise ValueError("Wi-Fi SSID and password are required")
    return ssid, password


class BleProvisioningService:
    """Own one short-lived BlueZ GATT provisioning session."""

    def __init__(self, *, adapter: str = "hci0", pairing_code_provider: Callable[[], str | None] | None = None) -> None:
        self._adapter = adapter
        self._pairing_code_provider = pairing_code_provider
        self._thread: Thread | None = None
        self._stop = Event()
        self._setup_code = ""
        self._on_credentials: Callable[[str, str], None] | None = None

    def start(self, setup_code: str, on_credentials: Callable[[str, str], None]) -> None:
        """Advertise the setup service until credentials arrive or the session stops."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._setup_code = setup_code
        self._on_credentials = on_credentials
        self._stop.clear()
        self._thread = Thread(target=self._run, name="ticker-ble-provisioning", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop advertising after Wi-Fi provisioning completes."""

        self._stop.set()

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except (ImportError, OSError, RuntimeError) as error:
            # The application records the setup state. This message is useful on
            # a Pi when BlueZ is disabled or the system D-Bus is unavailable.
            print(f"BLE provisioning unavailable: {error}", flush=True)

    async def _run_async(self) -> None:
        try:
            from dbus_next import BusType
            from dbus_next.aio import MessageBus
            from dbus_next.service import ServiceInterface
        except ImportError as error:
            raise ImportError("install dbus-next and enable bluetooth.service") from error

        challenge = secrets.token_bytes(16)
        pairing_code = self._pairing_code_provider() if self._pairing_code_provider is not None else None
        state = _BleSessionState(self._setup_code, challenge, pairing_code, self._on_credentials, self._stop)
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        root = _BleObjectManager(ServiceInterface, state)
        service = _BleService(ServiceInterface, state)
        challenge_characteristic = _BleCharacteristic(ServiceInterface, state, "challenge", BLE_CHALLENGE_UUID, ["read"])
        credentials_characteristic = _BleCharacteristic(ServiceInterface, state, "credentials", BLE_CREDENTIALS_UUID, ["write"])
        result_characteristic = _BleCharacteristic(ServiceInterface, state, "result", BLE_RESULT_UUID, ["read"])
        pairing_characteristic = _BleCharacteristic(ServiceInterface, state, "pairing", BLE_PAIRING_UUID, ["read"])
        paths = {
            "/com/sportsticker": root,
            "/com/sportsticker/service": service,
            "/com/sportsticker/service/challenge": challenge_characteristic,
            "/com/sportsticker/service/credentials": credentials_characteristic,
            "/com/sportsticker/service/result": result_characteristic,
            "/com/sportsticker/service/pairing": pairing_characteristic,
        }
        for path, interface in paths.items():
            bus.export(path, interface)
        adapter_path = f"/org/bluez/{self._adapter}"
        introspection = await bus.introspect("org.bluez", adapter_path)
        adapter = bus.get_proxy_object("org.bluez", adapter_path, introspection)
        manager = adapter.get_interface("org.bluez.GattManager1")
        advertisement = _BleAdvertisement(ServiceInterface)
        bus.export("/com/sportsticker/advertisement", advertisement)
        ad_manager = adapter.get_interface("org.bluez.LEAdvertisingManager1")
        await manager.call_register_application("/com/sportsticker", {})
        await ad_manager.call_register_advertisement("/com/sportsticker/advertisement", {})
        try:
            while not self._stop.is_set() and not state.completed:
                await asyncio.sleep(0.25)
        finally:
            try:
                await ad_manager.call_unregister_advertisement("/com/sportsticker/advertisement")
            except Exception:
                pass
            try:
                await manager.call_unregister_application("/com/sportsticker")
            except Exception:
                pass
            bus.disconnect()


class _BleSessionState:
    def __init__(self, setup_code: str, challenge: bytes, pairing_code: str | None, callback: Callable[[str, str], None] | None, stop: Event) -> None:
        self.setup_code = setup_code
        self.challenge = challenge
        self.pairing_code = pairing_code
        self.callback = callback
        self.stop = stop
        self.chunks: dict[int, str] = {}
        self.total: int | None = None
        self.result = b"WAITING"
        self.failures = 0
        self.completed = False

    def write(self, value: bytes) -> None:
        try:
            prefix, encoded = value.decode("ascii").split(":", 1)
            index_text, total_text = prefix.split("/", 1)
            index, total = int(index_text), int(total_text)
            if total <= 0 or total > 32 or index < 0 or index >= total:
                raise ValueError("invalid BLE chunk")
            if self.total is None:
                self.total = total
            if self.total != total:
                raise ValueError("BLE chunk total changed")
            self.chunks[index] = encoded
            if len(self.chunks) != total:
                return
            payload = base64.b64decode("".join(self.chunks[i] for i in range(total)))
            ssid, password = decrypt_credentials(payload, self.setup_code, self.challenge)
            self.result = b"OK"
            self.completed = True
            self.stop.set()
            if self.callback is not None:
                Thread(target=self.callback, args=(ssid, password), daemon=True).start()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, base64.Error, UnicodeError) as error:
            self.failures += 1
            self.chunks.clear()
            self.total = None
            self.result = f"ERROR:{error}".encode("utf-8")[:200]
            if self.failures >= 5:
                self.completed = True
                self.stop.set()


def _load_dbus_types() -> tuple[Any, Any, Any, Any]:
    try:
        from dbus_next import Variant
        from dbus_next.constants import PropertyAccess
        from dbus_next.service import ServiceInterface, dbus_property, method
        return Variant, PropertyAccess, ServiceInterface, (dbus_property, method)
    except ImportError:
        class UnavailableInterface:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

        class UnavailableAccess:
            READ = "read"

        def unavailable_variant(signature: str, value: Any) -> tuple[str, Any]:
            return signature, value

        def no_op_property(*_args: Any, **_kwargs: Any):
            return property

        def no_op_method(*_args: Any, **_kwargs: Any):
            return lambda function: function

        return unavailable_variant, UnavailableAccess, UnavailableInterface, (no_op_property, no_op_method)


def _make_interface(base: Any, name: str) -> Any:
    return type(name, (base,), {})


_Variant, _PropertyAccess, _ServiceInterface, (_dbus_property, _method) = _load_dbus_types()


class _BleObjectManager(_ServiceInterface):
    def __init__(self, _base: Any, state: _BleSessionState) -> None:
        super().__init__("org.freedesktop.DBus.ObjectManager")
        self._state = state

    @_method()
    def GetManagedObjects(self) -> "a{oa{sa{sv}}}":
        return {
            "/com/sportsticker/service": {"org.bluez.GattService1": {"UUID": _Variant("s", BLE_SERVICE_UUID), "Primary": _Variant("b", True)}},
            "/com/sportsticker/service/challenge": {"org.bluez.GattCharacteristic1": {"UUID": _Variant("s", BLE_CHALLENGE_UUID), "Service": _Variant("o", "/com/sportsticker/service"), "Flags": _Variant("as", ["read"])}},
            "/com/sportsticker/service/credentials": {"org.bluez.GattCharacteristic1": {"UUID": _Variant("s", BLE_CREDENTIALS_UUID), "Service": _Variant("o", "/com/sportsticker/service"), "Flags": _Variant("as", ["write"])}},
            "/com/sportsticker/service/result": {"org.bluez.GattCharacteristic1": {"UUID": _Variant("s", BLE_RESULT_UUID), "Service": _Variant("o", "/com/sportsticker/service"), "Flags": _Variant("as", ["read"])}},
            "/com/sportsticker/service/pairing": {"org.bluez.GattCharacteristic1": {"UUID": _Variant("s", BLE_PAIRING_UUID), "Service": _Variant("o", "/com/sportsticker/service"), "Flags": _Variant("as", ["read"])}},
        }


class _BleService(_ServiceInterface):
    def __init__(self, _base: Any, _state: _BleSessionState) -> None:
        super().__init__("org.bluez.GattService1")

    @_dbus_property(access=_PropertyAccess.READ)
    def UUID(self) -> "s":
        return BLE_SERVICE_UUID

    @_dbus_property(access=_PropertyAccess.READ)
    def Primary(self) -> "b":
        return True


class _BleCharacteristic(_ServiceInterface):
    def __init__(self, _base: Any, state: _BleSessionState, kind: str, uuid: str, flags: list[str]) -> None:
        super().__init__("org.bluez.GattCharacteristic1")
        self._state, self._kind, self._uuid, self._flags = state, kind, uuid, flags

    @_dbus_property(access=_PropertyAccess.READ)
    def UUID(self) -> "s":
        return self._uuid

    @_dbus_property(access=_PropertyAccess.READ)
    def Service(self) -> "o":
        return "/com/sportsticker/service"

    @_dbus_property(access=_PropertyAccess.READ)
    def Flags(self) -> "as":
        return self._flags

    @_method()
    def ReadValue(self, _options: "a{sv}") -> "ay":
        if self._kind == "challenge":
            return self._state.challenge
        if self._kind == "pairing":
            return (self._state.pairing_code or "NONE").encode("ascii")
        return self._state.result

    @_method()
    def WriteValue(self, value: "ay", _options: "a{sv}") -> "":
        if self._kind == "credentials":
            self._state.write(bytes(value))


class _BleAdvertisement(_ServiceInterface):
    def __init__(self, _base: Any) -> None:
        super().__init__("org.bluez.LEAdvertisement1")

    @_dbus_property(access=_PropertyAccess.READ)
    def Type(self) -> "s":
        return "peripheral"

    @_dbus_property(access=_PropertyAccess.READ)
    def ServiceUUIDs(self) -> "as":
        return [BLE_SERVICE_UUID]

    @_dbus_property(access=_PropertyAccess.READ)
    def LocalName(self) -> "s":
        return BLE_LOCAL_NAME

    @_method()
    def Release(self) -> "":
        return None

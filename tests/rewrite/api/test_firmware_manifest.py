"""Exercise the version two mini firmware manifest contract."""

from __future__ import annotations

import pytest

from sports_ticker.bootstrap_v2 import create_backend_application
from sports_ticker.firmware import FirmwareManifest


pytestmark = pytest.mark.critical


MANIFEST = FirmwareManifest(
    version="mini-1.2.0",
    target="esp32s3",
    hardware="esp32-s3",
    binary_url="https://updates.example.test/mini-1.2.0.bin",
    size=65536,
    sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)


def _register_mini(client, ticker_id: str = "mini-firmware") -> dict:
    response = client.post(
        "/api/v2/devices/register",
        json={
            "device_id": ticker_id,
            "name": "Mini",
            "metadata": {},
            "profile": {
                "product_family": "mini",
                "hardware": "esp32-s3",
                "firmware": "mini-1.1.0",
                "display": {"width": 64, "height": 32, "panel_count": 1},
                "capabilities": {"modes": ["sports"], "asset_cache": False, "ota": True},
            },
        },
    )
    assert response.status_code == 201
    return response.get_json()


def test_device_can_fetch_matching_manifest_by_existing_ticker_identity(tmp_path) -> None:
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None, firmware_manifest=MANIFEST)
    try:
        client = app.test_client()
        _register_mini(client)

        response = client.get("/api/v2/tickers/mini-firmware/firmware?version=mini-1.2.0")

        assert response.status_code == 200
        assert response.get_json() == {
            "api_version": "v2",
            "ticker_id": "mini-firmware",
            "firmware": MANIFEST.to_mapping(),
        }
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_configured_firmware_binary_is_served_from_the_release_directory(tmp_path) -> None:
    binary = tmp_path / "mini-1.2.0.bin"
    binary.write_bytes(b"x" * MANIFEST.size)
    app = create_backend_application(
        tmp_path / "ticker.sqlite3",
        [],
        scheduler=None,
        firmware_manifest=MANIFEST,
        firmware_directory=tmp_path,
    )
    try:
        response = app.test_client().get("/firmware/mini-1.2.0.bin")
        assert response.status_code == 200
        assert response.data == b"x" * MANIFEST.size
        assert response.content_type == "application/octet-stream"
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_manifest_rejects_unknown_release_and_mismatched_hardware(tmp_path) -> None:
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None, firmware_manifest=MANIFEST)
    try:
        client = app.test_client()
        _register_mini(client)

        assert client.get("/api/v2/tickers/mini-firmware/firmware?version=missing").status_code == 404

        incompatible = FirmwareManifest(
            version=MANIFEST.version,
            target=MANIFEST.target,
            hardware="other-board",
            binary_url=MANIFEST.binary_url,
            size=MANIFEST.size,
            sha256=MANIFEST.sha256,
        )
        incompatible_app = create_backend_application(
            tmp_path / "incompatible.sqlite3",
            [],
            scheduler=None,
            firmware_manifest=incompatible,
        )
        try:
            incompatible_client = incompatible_app.test_client()
            _register_mini(incompatible_client, "mini-incompatible")
            response = incompatible_client.get("/api/v2/tickers/mini-incompatible/firmware")
            assert response.status_code == 409
        finally:
            incompatible_app.extensions["sports_ticker.backend_application"].close()
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_mini_update_request_requires_the_configured_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deploy-secret")
    app = create_backend_application(tmp_path / "ticker.sqlite3", [], scheduler=None, firmware_manifest=MANIFEST)
    try:
        client = app.test_client()
        _register_mini(client)
        headers = {"X-Deployment-Token": "deploy-secret"}

        accepted = client.post(
            "/api/v2/tickers/mini-firmware/updates",
            headers=headers,
            json={"version": MANIFEST.version},
        )
        rejected = client.post(
            "/api/v2/tickers/mini-firmware/updates",
            headers=headers,
            json={"version": "missing"},
        )

        assert accepted.status_code == 201
        assert rejected.status_code == 409
    finally:
        app.extensions["sports_ticker.backend_application"].close()


def test_mini_update_request_rejects_incompatible_hardware(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deploy-secret")
    incompatible = FirmwareManifest(
        version=MANIFEST.version,
        target=MANIFEST.target,
        hardware="other-board",
        binary_url=MANIFEST.binary_url,
        size=MANIFEST.size,
        sha256=MANIFEST.sha256,
    )
    app = create_backend_application(
        tmp_path / "ticker.sqlite3",
        [],
        scheduler=None,
        firmware_manifest=incompatible,
    )
    try:
        client = app.test_client()
        _register_mini(client)
        response = client.post(
            "/api/v2/tickers/mini-firmware/updates",
            headers={"X-Deployment-Token": "deploy-secret"},
            json={"version": MANIFEST.version},
        )
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "firmware_incompatible"
    finally:
        app.extensions["sports_ticker.backend_application"].close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size", 65535),
        ("sha256", "bad"),
        ("binary_url", "http://updates.example.test/image.bin"),
    ],
)
def test_manifest_validation_fails_closed(field: str, value: object) -> None:
    values = MANIFEST.to_mapping()
    values[field] = value
    with pytest.raises(ValueError):
        FirmwareManifest.from_mapping(values)

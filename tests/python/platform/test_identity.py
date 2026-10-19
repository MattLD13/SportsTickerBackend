from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ticker_core.platform import DeviceIdentityStore


def test_identity_store_persists_primary_identifier(tmp_path: Path) -> None:
    primary = tmp_path / "boot" / "ticker_id.txt"
    fallback = tmp_path / "ticker_id.txt"
    store = DeviceIdentityStore(primary, fallback, create_identifier=lambda: UUID(int=7))

    assert store.load() == "00000000-0000-0000-0000-000000000007"
    assert primary.read_text(encoding="utf-8") == "00000000-0000-0000-0000-000000000007"
    assert store.load() == "00000000-0000-0000-0000-000000000007"


def test_identity_store_uses_fallback_when_primary_cannot_be_created(tmp_path: Path) -> None:
    primary = tmp_path / "file-not-directory"
    primary.write_text("blocked", encoding="utf-8")
    fallback = tmp_path / "fallback" / "ticker_id.txt"
    store = DeviceIdentityStore(primary / "ticker_id.txt", fallback, create_identifier=lambda: UUID(int=8))

    assert store.load() == "00000000-0000-0000-0000-000000000008"
    assert fallback.read_text(encoding="utf-8") == "00000000-0000-0000-0000-000000000008"

"""Test safe device identity composition."""

import pytest
from ticker_core.composition import load_device_id

pytestmark = pytest.mark.critical


def test_device_identity_uses_explicit_value_and_windows_data_path(tmp_path, monkeypatch) -> None:
    """Keep desktop identity data outside the Windows boot drive."""
    monkeypatch.setenv("TICKER_DEVICE_ID", "desk-42")
    assert load_device_id(tmp_path, windows=True) == "desk-42"

    monkeypatch.delenv("TICKER_DEVICE_ID")
    identifier = load_device_id(tmp_path, windows=True)
    assert identifier
    assert (tmp_path / "ticker_id.txt").read_text(encoding="utf-8") == identifier

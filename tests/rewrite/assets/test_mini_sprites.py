"""Verify source identity, validated storage, refresh, and bounded asset persistence."""

import hashlib
import io
import json

from PIL import Image
import pytest

from sports_ticker.assets.mini_service import MiniSpriteService, SourceReply
from sports_ticker.assets.mini_sprite import SpritePolicy, WIRE_BYTES, encode_sprite, validate_sprite


def png(color):
    output = io.BytesIO()
    Image.new("RGBA", (23, 17), color).save(output, format="PNG")
    return output.getvalue()


def test_sprite_identity_includes_bytes_and_policy_and_wire_rejects_damage():
    source = png((255, 80, 20, 190))
    identity, body = encode_sprite(source)
    checksum = hashlib.sha256(body).hexdigest()
    assert len(body) == WIRE_BYTES == 705
    assert validate_sprite(body, checksum)
    assert encode_sprite(source) == (identity, body)
    assert encode_sprite(png((10, 80, 20, 190)))[0] != identity
    assert SpritePolicy(method="new").identity(source) != identity
    assert SpritePolicy(pipeline_version=2).identity(source) != identity
    for damaged in (body[:-1], body + b"\0", bytes([body[0] ^ 1]) + body[1:]):
        assert not validate_sprite(damaged, checksum)
    unsupported = bytearray(body)
    unsupported[6] = 19
    assert not validate_sprite(bytes(unsupported), hashlib.sha256(unsupported).hexdigest())


def test_persisted_reuse_conditional_refresh_same_url_changes_and_policy_invalidation(tmp_path):
    now = [1000.0]
    source = [png((220, 60, 20, 255))]
    calls = []

    def fetch(url, etag, modified):
        calls.append((url, etag, modified))
        return SourceReply(source[0], f'"{len(calls)}"', "source-date")

    def create(**kwargs):
        return MiniSpriteService(tmp_path, fetcher=fetch, clock=lambda: now[0], refresh_seconds=30, **kwargs)

    service = create()
    try:
        assert service.reference("https://a.espncdn.com/team.png")["state"] == "pending"
        service.wait()
        first = service.reference("https://a.espncdn.com/team.png")
        assert first["state"] == "ready"
        for _ in range(10):
            assert service.reference("https://a.espncdn.com/team.png")["asset_id"] == first["asset_id"]
        assert len(calls) == 1
    finally:
        service.close()
    service = create()
    try:
        assert service.reference("https://a.espncdn.com/team.png")["asset_id"] == first["asset_id"]
        assert len(calls) == 1
        source[0] = png((10, 200, 20, 255))
        now[0] += 31
        assert service.reference("https://a.espncdn.com/team.png")["refreshing"]
        service.wait()
        second = service.reference("https://a.espncdn.com/team.png")
        assert second["asset_id"] != first["asset_id"]
        assert calls[-1][1:] == ('"1"', "source-date")
        assert service.read(first["asset_id"]) is not None
    finally:
        service.close()
    service = create()
    assert service.read(first["asset_id"]) is not None
    service.close()
    service = create(policy=SpritePolicy(method="new"))
    try:
        service.reference("https://a.espncdn.com/team.png")
        service.wait()
        assert service.reference("https://a.espncdn.com/team.png")["asset_id"] != second["asset_id"]
    finally:
        service.close()


def test_source_304_preserves_sprite_and_corrupt_files_never_publish_ready(tmp_path):
    now = [100.0]
    calls = []

    def fetch(url, etag, modified):
        calls.append(etag)
        return SourceReply(None if etag else png((10, 20, 30, 255)), '"same"')

    service = MiniSpriteService(tmp_path, fetcher=fetch, clock=lambda: now[0], refresh_seconds=10)
    service.reference("https://a.espncdn.com/a.png")
    service.wait()
    first = service.reference("https://a.espncdn.com/a.png")
    now[0] += 11
    service.reference("https://a.espncdn.com/a.png")
    service.wait()
    assert service.reference("https://a.espncdn.com/a.png")["asset_id"] == first["asset_id"]
    assert calls == ["", '"same"']
    path = tmp_path / f'{first["asset_id"]}.mts'
    damaged = bytearray(path.read_bytes())
    damaged[100] ^= 1
    path.write_bytes(damaged)
    assert service.read(first["asset_id"]) is None
    service.close()
    service = MiniSpriteService(tmp_path, fetcher=fetch, clock=lambda: now[0])
    try:
        assert service.reference("https://a.espncdn.com/a.png")["state"] == "pending"
        service.wait()
        assert service.reference("https://a.espncdn.com/a.png")["state"] == "ready"
    finally:
        service.close()


def test_cache_bounds_and_failed_writes_leave_the_previous_file_valid(tmp_path, monkeypatch):
    service = MiniSpriteService(tmp_path, max_entries=1, fetcher=lambda url, *_: SourceReply(png((len(url), 0, 80, 255))))
    try:
        for url in ("first", "second"):
            service.reference(url)
            service.wait()
        assert len(list(tmp_path.glob("*.mts"))) == 1
        index = json.loads((tmp_path / "index.json").read_text())
        assert len(index["entries"]) == len(index["checksums"]) == 1
        asset = next(tmp_path.glob("*.mts"))
        before = asset.read_bytes()

        def fail_replace(*args):
            raise OSError("power loss before rename")

        monkeypatch.setattr("sports_ticker.assets.mini_service.os.replace", fail_replace)
        with pytest.raises(OSError):
            service._atomic_file(asset, b"incomplete")
        assert asset.read_bytes() == before
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        service.close()

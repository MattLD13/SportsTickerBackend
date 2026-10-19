from __future__ import annotations

import json

from PIL import Image
import pytest

from tools.mini.capture_mini import CapturedFrame, FrameReceiver, checksum, save_frame


pytestmark = pytest.mark.critical


def wire_frame() -> tuple[bytes, dict, list[str]]:
    pixels = bytes((index * 29 + 7) & 255 for index in range(6144))
    metadata = {"v": 1, "id": 7, "width": 64, "height": 32, "format": "rgb888", "bytes": 6144,
                "fnv1a32": checksum(pixels), "pane": {"kind": "sports", "item_id": "live", "index": 0}}
    chunks = [f"MINI_PIX:00000007:{offset:04x}:{pixels[offset:offset + 16].hex()}" for offset in range(0, 6144, 16)]
    return pixels, metadata, chunks


def test_complete_frame_keeps_every_rgb_byte_and_packet_order() -> None:
    pixels, metadata, chunks = wire_frame()
    receiver = FrameReceiver()
    receiver.accept("MINI_FRAME_BEGIN:" + json.dumps(metadata))
    for chunk in reversed(chunks):
        assert receiver.accept(chunk) is None
    frame = receiver.accept(f'MINI_FRAME_END:00000007:{metadata["fnv1a32"]:08x}')
    assert frame is not None
    assert frame.pixels == pixels
    assert frame.metadata == metadata


@pytest.mark.parametrize("failure", ["missing", "checksum", "duplicate", "bounds", "wrong_frame"])
def test_receiver_rejects_incomplete_or_corrupt_frames(failure: str) -> None:
    _, metadata, chunks = wire_frame()
    receiver = FrameReceiver()
    receiver.accept("MINI_FRAME_BEGIN:" + json.dumps(metadata))
    for chunk in chunks[:-1]:
        receiver.accept(chunk)
    with pytest.raises(ValueError):
        if failure == "duplicate": receiver.accept(chunks[0])
        elif failure == "bounds": receiver.accept("MINI_PIX:00000007:ffff:" + "00" * 16)
        elif failure == "wrong_frame": receiver.accept(chunks[-1].replace("00000007", "00000008"))
        elif failure == "checksum":
            receiver.accept(chunks[-1])
            receiver.accept("MINI_FRAME_END:00000007:00000000")
        else: receiver.accept(f'MINI_FRAME_END:00000007:{metadata["fnv1a32"]:08x}')


def test_receiver_rejects_unknown_dimensions() -> None:
    _, metadata, _ = wire_frame()
    metadata["width"] = 384
    with pytest.raises(ValueError, match="unsupported"):
        FrameReceiver().accept("MINI_FRAME_BEGIN:" + json.dumps(metadata))


def test_saved_matrix_and_png_match_the_wire_pixels(tmp_path) -> None:
    pixels, metadata, _ = wire_frame()
    path = save_frame(CapturedFrame(metadata, pixels), tmp_path, 1)
    with Image.open(path) as image:
        assert image.size == (64, 32)
        assert image.tobytes() == pixels
    matrix = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["matrix"]
    assert len(matrix) == 32 and all(len(row) == 64 for row in matrix)
    assert bytes.fromhex("".join(value for row in matrix for value in row)) == pixels
    assert len(path.with_suffix(".matrix.txt").read_text(encoding="utf-8").splitlines()) == 32

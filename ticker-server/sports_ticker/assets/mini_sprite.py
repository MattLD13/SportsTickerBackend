"""Define the content identity and wire bytes for one Mini sports logo variant."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import struct
from PIL import Image

from .images import prepare_contained, prepare_contained_native_grid


SIZE = 18
PIPELINE_VERSION = 1
HEADER = struct.Struct("<4sBBBBBBHHH")
PIXEL_BYTES = SIZE * SIZE * 2
MASK_BYTES = (SIZE * SIZE + 7) // 8
WIRE_BYTES = HEADER.size + PIXEL_BYTES + MASK_BYTES


@dataclass(frozen=True, slots=True)
class SpritePolicy:
    """Identify every image preparation decision for the Mini variant."""

    method: str = "old"
    pipeline_version: int = PIPELINE_VERSION

    def identity(self, source: bytes) -> str:
        value = {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "method": self.method, "pipeline_version": self.pipeline_version,
            "width": SIZE, "height": SIZE, "format": "rgb565-le",
            "mask": "row-major-lsb", "alpha": "premultiplied-black",
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def encode_sprite(source: bytes, policy: SpritePolicy = SpritePolicy()) -> tuple[str, bytes]:
    """Prepare a logo once and encode its fixed row order and opacity mask."""
    if policy.method not in {"old", "new"} or not 1 <= policy.pipeline_version <= 255:
        raise ValueError("invalid Mini sprite policy")
    with Image.open(io.BytesIO(source)) as image:
        if image.width > 2048 or image.height > 2048:
            raise ValueError("logo source dimensions exceed the preparation limit")
    prepare = prepare_contained if policy.method == "old" else prepare_contained_native_grid
    image = prepare(source, (SIZE, SIZE))
    pixels = bytearray()
    mask = bytearray(MASK_BYTES)
    for index, (red, green, blue, alpha) in enumerate(image.getdata()):
        if alpha:
            mask[index // 8] |= 1 << (index % 8)
        red, green, blue = red * alpha // 255, green * alpha // 255, blue * alpha // 255
        pixels.extend(struct.pack("<H", ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)))
    header = HEADER.pack(b"MTS1", 1, policy.pipeline_version, SIZE, SIZE, 1, 1, PIXEL_BYTES, MASK_BYTES, 0)
    return policy.identity(source), header + pixels + mask


def validate_sprite(body: bytes, checksum: str) -> bool:
    """Reject damaged files and unsupported binary layouts."""
    if len(body) != WIRE_BYTES or hashlib.sha256(body).hexdigest() != checksum:
        return False
    fields = HEADER.unpack_from(body)
    return (
        fields == (b"MTS1", 1, PIPELINE_VERSION, SIZE, SIZE, 1, 1, PIXEL_BYTES, MASK_BYTES, 0)
        and body[-1] & 0xF0 == 0
    )

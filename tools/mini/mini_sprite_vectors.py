"""Generate Python wire vectors for the native Mini sprite checks."""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ticker.shared.images import prepare_contained
from ticker.server.mini_assets.mini_sprite import encode_sprite


def generate(output: Path) -> None:
    """Write three independent pixel and mask reference vectors."""
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for number in range(3):
        source = Image.new("RGBA", (36, 28), (0, 0, 0, 0))
        draw = ImageDraw.Draw(source)
        draw.rectangle((3, 2, 30, 24), fill=(230, 40 + number * 60, 90, 255))
        draw.rectangle((10, 6, 22, 20), fill=(20, 200, 250, 64 + number * 70))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        raw = buffer.getvalue()
        identity, wire = encode_sprite(raw)
        image = prepare_contained(raw, (18, 18))
        pixels, mask = bytearray(), bytearray()
        for red, green, blue, alpha in image.getdata():
            red, green, blue = red * alpha // 255, green * alpha // 255, blue * alpha // 255
            value = ((red & 248) << 8) | ((green & 252) << 3) | (blue >> 3)
            pixels.extend(value.to_bytes(2, "little"))
            mask.append(int(alpha != 0))
        (output / f"{identity}.mts").write_bytes(wire)
        (output / f"{identity}.pixels").write_bytes(pixels)
        (output / f"{identity}.mask").write_bytes(mask)
        manifest.append(f"{identity} {hashlib.sha256(wire).hexdigest()}")
    (output / "manifest.txt").write_text("\n".join(manifest) + "\n")
    print(f"Generated {len(manifest)} sprite vectors in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)

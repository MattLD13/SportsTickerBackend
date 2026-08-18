"""Pure image processors shared by every display family."""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageFilter


def prepare_contained(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Fit one source image inside a transparent target image."""
    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGBA").convert("RGBa")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    image = image.convert("RGBA")
    target = Image.new("RGBA", size, (0, 0, 0, 0))
    target.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return _enhance_dark_image(target)


def prepare_car(raw: bytes, size: tuple[int, int], *, mirror: bool = False) -> Image.Image:
    """Remove a white car field and fit the car into its target box."""
    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGBA")
    image = _crop_nonwhite(image)
    image.thumbnail((max(400, size[0] * 4), max(100, size[1] * 4)), Image.Resampling.LANCZOS)
    image = remove_border_background(image)
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    if mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    image.thumbnail(size, Image.Resampling.LANCZOS)
    return image


def prepare_imsa_car(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Prepare and mirror an IMSA car to face right."""
    return prepare_car(raw, size, mirror=True)


def prepare_nascar_car(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Prepare and mirror a NASCAR car to face right."""
    return prepare_car(raw, size, mirror=True)


def remove_border_background(image: Image.Image, tolerance: int = 20) -> Image.Image:
    """Clear near-white pixels connected to an image edge."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    threshold = 255 - tolerance
    seen: set[tuple[int, int]] = set()
    pending: list[tuple[int, int]] = []

    def add(x: int, y: int) -> None:
        if (x, y) in seen:
            return
        red, green, blue, _ = pixels[x, y]
        if red >= threshold and green >= threshold and blue >= threshold:
            seen.add((x, y))
            pending.append((x, y))

    for x in range(width):
        add(x, 0)
        add(x, height - 1)
    for y in range(height):
        add(0, y)
        add(width - 1, y)
    while pending:
        x, y = pending.pop()
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= next_x < width and 0 <= next_y < height:
                add(next_x, next_y)
    for x, y in seen:
        red, green, blue, _ = pixels[x, y]
        pixels[x, y] = (red, green, blue, 0)
    return rgba


def _crop_nonwhite(image: Image.Image) -> Image.Image:
    """Crop a source image before car processing."""
    pixels = image.load()
    changed = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if pixels[x, y][3] and not all(channel >= 240 for channel in pixels[x, y][:3])
    ]
    if not changed:
        return image
    xs, ys = zip(*changed)
    padding = 8
    return image.crop((max(0, min(xs) - padding), max(0, min(ys) - padding), min(image.width, max(xs) + padding + 1), min(image.height, max(ys) + padding + 1)))


def _enhance_dark_image(image: Image.Image) -> Image.Image:
    """Outline images that would disappear on the black panel."""
    opaque = [pixel for pixel in image.getdata() if pixel[3] > 200]
    if not opaque:
        return image
    dark = sum(0.2126 * red + 0.7152 * green + 0.0722 * blue < 40 for red, green, blue, _ in opaque)
    if dark / len(opaque) < 0.92:
        return image
    alpha = image.getchannel("A")
    ring = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(3)), alpha)
    outlined = Image.new("RGBA", image.size, (0, 0, 0, 0))
    outlined.paste(Image.new("RGBA", image.size, (245, 245, 245, 230)), mask=ring)
    outlined.alpha_composite(image)
    return outlined

"""Render a compact backend-disconnect indicator."""

from PIL import Image, ImageDraw


class ConnectionLostOverlay:
    """Draw a crossed server icon over a complete panel frame."""

    def apply(self, frame: Image.Image) -> Image.Image:
        """Return the frame with a top-right connection indicator."""
        image = frame.convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        left = image.width - 12
        draw.rounded_rectangle((left, 0, image.width - 1, 9), radius=2, fill=(0, 0, 0, 215))
        draw.rectangle((left + 2, 2, left + 8, 7), outline=(210, 215, 225, 255))
        draw.line((left + 3, 4, left + 7, 4), fill=(100, 110, 125, 255))
        draw.point((left + 3, 6), fill=(255, 180, 20, 255))
        draw.line((left + 1, 8, left + 10, 0), fill=(255, 70, 70, 255), width=2)
        image.alpha_composite(overlay)
        return image.convert("RGB")

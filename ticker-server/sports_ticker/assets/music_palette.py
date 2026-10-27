"""Own album accent colors for Ticker Six and Mini artwork."""
import colorsys

from PIL import Image, ImageStat


def artwork_colors(image: Image.Image | None, dominant=(29, 185, 84), spindle="black"):
    """Brighten dark album colors and preserve readable neutral accents."""
    if image is None:
        return dominant, spindle
    red, green, blue = ImageStat.Stat(image.convert("RGB")).mean[:3]
    brightness = 0.299 * red + 0.587 * green + 0.114 * blue
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    saturation = 0.0 if saturation < 0.2 else min(1.0, saturation * 1.5) if saturation < 0.5 else saturation
    value = 0.5 if value < 0.3 else min(1.0, value * 1.3) if value < 0.8 else value
    result = colorsys.hsv_to_rgb(hue, saturation, value)
    return tuple(int(channel * 255) for channel in result), "white" if brightness < 140 else "black"

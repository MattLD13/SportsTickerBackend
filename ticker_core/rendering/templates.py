"""Keep bounded immutable image templates for renderer-owned fixed layers."""

from collections import OrderedDict
from hashlib import sha256

from PIL import Image


def image_key(image: Image.Image | None):
    """Identify image pixels and logo outline inputs without retaining the image."""
    if image is None:
        return None
    return (image.size, image.mode, sha256(image.tobytes()).digest(),
            getattr(image, "logo_rendering_outline", None), getattr(image, "logo_rendering_cutoff", None))


class ImageTemplates:
    """Reuse complete fixed layers while bounding entry count and pixel memory."""

    def __init__(self, *, capacity: int = 256, max_bytes: int = 2 * 1024 * 1024):
        if capacity <= 0 or max_bytes <= 0:
            raise ValueError("Template limits must be positive")
        self._capacity, self._max_bytes = capacity, max_bytes
        self._items = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def render(self, key, build):
        """Return a private copy of a template for dynamic drawing."""
        image = self._items.get(key)
        if image is not None:
            self.hits += 1
            self._items.move_to_end(key)
            return image.copy()
        self.misses += 1
        image = build()
        size = image.width * image.height * len(image.getbands())
        if size <= self._max_bytes:
            self._items[key] = image
            self._bytes += size
            while len(self._items) > self._capacity or self._bytes > self._max_bytes:
                _, old = self._items.popitem(last=False)
                self._bytes -= old.width * old.height * len(old.getbands())
        return image.copy()

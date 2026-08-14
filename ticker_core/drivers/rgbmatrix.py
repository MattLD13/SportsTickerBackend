"""HUB75 RGB matrix output."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .memory import _brightness, _prepare_frame


class RgbMatrixUnavailableError(RuntimeError):
    """Raised when the Pi RGB matrix library is unavailable."""


@dataclass(frozen=True, slots=True)
class RgbMatrixSettings:
    """Hardware settings for the six-panel HUB75 chain."""

    width: int = 384
    height: int = 32
    panel_columns: int = 64
    parallel: int = 1
    hardware_mapping: str = "regular"
    gpio_slowdown: int = 1
    pwm_bits: int = 11
    pwm_lsb_nanoseconds: int = 130
    hardware_pulsing: bool = True
    luminance_correction: bool = True
    show_refresh_rate: bool = False
    refresh_rate_limit_hz: int = 100

    def __post_init__(self) -> None:
        if self.width % self.panel_columns:
            raise ValueError("Display width must divide evenly into panel columns.")
        if self.height <= 0 or self.width <= 0:
            raise ValueError("Display dimensions must be positive.")
        if self.refresh_rate_limit_hz < 0:
            raise ValueError("Refresh rate limit cannot be negative.")

    @property
    def chain_length(self) -> int:
        return self.width // self.panel_columns

    @classmethod
    def from_environment(
        cls,
        *,
        module_probe: Callable[[], bool] | None = None,
        environment: dict[str, str] | None = None,
    ) -> "RgbMatrixSettings":
        values = os.environ if environment is None else environment
        requested_pulsing = values.get("TICKER_HW_PULSE", "").strip().lower()
        if requested_pulsing:
            hardware_pulsing = requested_pulsing in {"1", "true"}
        else:
            probe = _sound_module_loaded if module_probe is None else module_probe
            hardware_pulsing = not probe()
        return cls(
            gpio_slowdown=int(values.get("TICKER_GPIO_SLOWDOWN") or 1),
            pwm_bits=int(values.get("TICKER_PWM_BITS") or 11),
            pwm_lsb_nanoseconds=int(values.get("TICKER_PWM_LSB_NS") or 130),
            hardware_pulsing=hardware_pulsing,
            luminance_correction=values.get("TICKER_LUMINANCE", "").strip().lower() not in {"0", "false"},
            show_refresh_rate=values.get("TICKER_SHOW_REFRESH", "").strip().lower() in {"1", "true"},
            refresh_rate_limit_hz=int(values.get("TICKER_MATRIX_REFRESH_HZ") or 100),
        )


class RgbMatrixFrameSink:
    """Present frames with an RGBMatrix vertical-sync swap."""

    def __init__(self, matrix: Any, *, width: int = 384, height: int = 32) -> None:
        self.width = width
        self.height = height
        self._matrix = matrix
        self._canvas = self._create_canvas(matrix)
        self.brightness = 100
        self.inverted = False

    @classmethod
    def create(cls, settings: RgbMatrixSettings | None = None) -> "RgbMatrixFrameSink":
        """Create a sink with the installed Pi RGB matrix library."""
        active_settings = RgbMatrixSettings.from_environment() if settings is None else settings
        try:
            module = importlib.import_module("rgbmatrix")
        except ImportError as error:
            raise RgbMatrixUnavailableError("The rgbmatrix package is not installed.") from error
        options = module.RGBMatrixOptions()
        options.rows = active_settings.height
        options.cols = active_settings.panel_columns
        options.chain_length = active_settings.chain_length
        options.parallel = active_settings.parallel
        options.hardware_mapping = active_settings.hardware_mapping
        options.gpio_slowdown = active_settings.gpio_slowdown
        options.disable_hardware_pulsing = not active_settings.hardware_pulsing
        options.drop_privileges = False
        options.pwm_bits = active_settings.pwm_bits
        options.pwm_lsb_nanoseconds = active_settings.pwm_lsb_nanoseconds
        if active_settings.refresh_rate_limit_hz:
            options.limit_refresh_rate_hz = active_settings.refresh_rate_limit_hz
        if active_settings.show_refresh_rate:
            options.show_refresh_rate = 1
        matrix = module.RGBMatrix(options=options)
        if hasattr(matrix, "luminanceCorrect"):
            matrix.luminanceCorrect = active_settings.luminance_correction
        return cls(matrix, width=active_settings.width, height=active_settings.height)

    def present(
        self,
        image: Image.Image,
        *,
        brightness: int = 100,
        inverted: bool = False,
    ) -> None:
        frame = _prepare_frame(image, self.width, self.height, inverted)
        target_brightness = _brightness(brightness)
        self.brightness = target_brightness
        self.inverted = inverted
        if self._canvas is not None:
            self._canvas.brightness = target_brightness
            self._canvas.SetImage(frame)
            self._canvas = self._matrix.SwapOnVSync(self._canvas)
            return
        self._matrix.brightness = target_brightness
        self._matrix.SetImage(frame)

    def clear(self) -> None:
        self.present(Image.new("RGB", (self.width, self.height)), brightness=self.brightness)

    @staticmethod
    def _create_canvas(matrix: Any) -> Any | None:
        create = getattr(matrix, "CreateFrameCanvas", None)
        swap = getattr(matrix, "SwapOnVSync", None)
        if not callable(create) or not callable(swap):
            return None
        return create()


def _sound_module_loaded() -> bool:
    try:
        return "snd_bcm2835" in Path("/proc/modules").read_text(encoding="utf-8")
    except OSError:
        return True

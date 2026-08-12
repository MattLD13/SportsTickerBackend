from __future__ import annotations

from ticker_core.drivers import RgbMatrixSettings


def test_settings_preserve_six_panel_geometry() -> None:
    settings = RgbMatrixSettings()

    assert settings.width == 384
    assert settings.height == 32
    assert settings.chain_length == 6


def test_environment_can_disable_hardware_pulsing() -> None:
    settings = RgbMatrixSettings.from_environment(
        module_probe=lambda: False,
        environment={"TICKER_HW_PULSE": "0", "TICKER_PWM_BITS": "8"},
    )

    assert not settings.hardware_pulsing
    assert settings.pwm_bits == 8


def test_environment_uses_module_probe_when_pulsing_is_unset() -> None:
    settings = RgbMatrixSettings.from_environment(module_probe=lambda: True, environment={})

    assert not settings.hardware_pulsing

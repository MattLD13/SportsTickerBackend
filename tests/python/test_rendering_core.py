"""Tests for the render context."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from ticker_core.ui.frame import RenderContext

pytestmark = pytest.mark.critical


def test_context_keeps_the_injected_time() -> None:
    """The context uses the caller supplied time."""
    now = datetime(2026, 8, 11, 9, 30)

    context = RenderContext(now=now)

    assert context.now is now
    with pytest.raises(FrozenInstanceError):
        context.now = datetime(2026, 8, 11, 9, 31)

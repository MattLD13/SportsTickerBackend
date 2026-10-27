"""Preserve nested source values at the shared immutable boundary."""

import pytest

from sports_ticker.immutable import freeze


def test_freeze_copies_nested_values_without_changing_mapping_keys():
    source = {1: [bytearray(b"a"), {"tags": {"one", "two"}}]}
    result = freeze(source)
    source[1][0][0] = ord("b")
    source[1][1]["tags"].add("three")
    assert result[1][0] == b"a"
    assert result[1][1]["tags"] == frozenset({"one", "two"})
    with pytest.raises(TypeError):
        result[1] = ()

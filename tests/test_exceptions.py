"""
Tests that verify logic local to exceptions.
"""
from __future__ import annotations

import h2.exceptions


class TestExceptions:
    def test_stream_id_too_low_prints_properly(self) -> None:
        x = h2.exceptions.StreamIDTooLowError(5, 10)

        assert str(x) == "StreamIDTooLowError: 5 is lower than 10"

"""Regression test for oversized HEADERS frames carrying inline priority."""

from __future__ import annotations

import random

import pytest

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import RequestReceived
from h2.settings import SettingCodes

MAX_FRAME_SIZE = 16384


def _new_connection(client_side: bool) -> H2Connection:
    return H2Connection(H2Configuration(client_side=client_side))


def _large_headers() -> list[tuple[str, bytes]]:
    # Deterministic, incompressible payload: well over one frame on its own.
    payload = random.Random(0).randbytes(50_000)  # noqa: S311 - deterministic, not cryptographic
    # NUL/LF/CR are illegal in header values; swap them for safe bytes.
    payload = payload.translate(
        bytes.maketrans(bytes([0, 10, 13]), bytes([120, 121, 122])),
    )
    payload = b"x" + payload + b"x"
    return [
        (":method", "GET"),
        (":scheme", "https"),
        (":authority", "example.com"),
        (":path", "/"),
        ("x-large", payload),
    ]


def _frame_lengths(data: bytes) -> list[int]:
    lengths = []
    offset = 0
    while offset < len(data):
        body_len = int.from_bytes(data[offset:offset + 3], "big")
        lengths.append(body_len)
        offset += 9 + body_len
    assert offset == len(data)
    return lengths


@pytest.mark.parametrize("priority_weight", [16, None])
def test_large_headers_with_optional_priority(
    priority_weight: int | None,
) -> None:
    """Large header blocks must fit alongside optional inline priority."""
    client = _new_connection(client_side=True)
    server = _new_connection(client_side=False)

    # Pin both peers to the same SETTINGS_MAX_FRAME_SIZE.
    client.local_settings[SettingCodes.MAX_FRAME_SIZE] = MAX_FRAME_SIZE
    server.local_settings[SettingCodes.MAX_FRAME_SIZE] = MAX_FRAME_SIZE

    client.initiate_connection()
    server.initiate_connection()
    server.receive_data(client.data_to_send())
    client.receive_data(server.data_to_send())
    client.clear_outbound_data_buffer()

    priority_kwargs = (
        {} if priority_weight is None else {"priority_weight": priority_weight}
    )
    client.send_headers(1, _large_headers(), end_stream=True, **priority_kwargs)

    data = client.data_to_send()
    lengths = _frame_lengths(data)
    assert lengths
    assert all(length <= MAX_FRAME_SIZE for length in lengths)

    events = server.receive_data(data)
    requests = [event for event in events if isinstance(event, RequestReceived)]
    assert len(requests) == 1
    if priority_weight is None:
        assert requests[0].priority_updated is None
    else:
        assert requests[0].priority_updated is not None
        assert requests[0].priority_updated.weight == priority_weight

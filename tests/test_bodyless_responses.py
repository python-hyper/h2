"""RFC 9113 bodyless responses may carry a non-zero content-length."""

from __future__ import annotations

import pytest

import h2.connection
import h2.events
import h2.exceptions

REQUEST_HEADERS = [
    (b":authority", b"example.com"),
    (b":path", b"/"),
    (b":scheme", b"https"),
    (b":method", b"POST"),
]


def _open_stream(frame_factory) -> h2.connection.H2Connection:
    connection = h2.connection.H2Connection()
    connection.initiate_connection()
    connection.send_headers(1, REQUEST_HEADERS, end_stream=True)
    return connection


@pytest.mark.parametrize("status", [b"204", b"304"])
def test_bodyless_response_accepts_content_length_with_empty_data(
    frame_factory, status: bytes
) -> None:
    connection = _open_stream(frame_factory)
    headers = frame_factory.build_headers_frame(
        [(b":status", status), (b"content-length", b"1234")]
    )
    events = connection.receive_data(headers.serialize())
    assert isinstance(events[0], h2.events.ResponseReceived)

    data = frame_factory.build_data_frame(b"", flags=["END_STREAM"])
    events = connection.receive_data(data.serialize())

    assert isinstance(events[0], h2.events.DataReceived)
    assert isinstance(events[1], h2.events.StreamEnded)


@pytest.mark.parametrize("status", [b"204", b"304"])
def test_bodyless_response_accepts_content_length_when_headers_end_stream(
    frame_factory, status: bytes
) -> None:
    connection = _open_stream(frame_factory)
    headers = frame_factory.build_headers_frame(
        [(b":status", status), (b"content-length", b"1234")],
        flags=["END_STREAM"],
    )

    events = connection.receive_data(headers.serialize())

    assert isinstance(events[0], h2.events.ResponseReceived)
    assert isinstance(events[1], h2.events.StreamEnded)


def test_200_with_content_length_and_empty_data_is_still_rejected(frame_factory) -> None:
    connection = _open_stream(frame_factory)
    headers = frame_factory.build_headers_frame(
        [(b":status", b"200"), (b"content-length", b"1234")]
    )
    connection.receive_data(headers.serialize())

    data = frame_factory.build_data_frame(b"", flags=["END_STREAM"])
    with pytest.raises(h2.exceptions.InvalidBodyLengthError):
        connection.receive_data(data.serialize())


def test_bodyless_response_with_actual_data_is_rejected(frame_factory) -> None:
    connection = _open_stream(frame_factory)
    headers = frame_factory.build_headers_frame(
        [(b":status", b"304"), (b"content-length", b"1234")]
    )
    connection.receive_data(headers.serialize())

    data = frame_factory.build_data_frame(b"\x01", flags=["END_STREAM"])
    with pytest.raises(h2.exceptions.InvalidBodyLengthError):
        connection.receive_data(data.serialize())

"""Content-Length must be satisfied when END_STREAM rides on a header block."""

from __future__ import annotations

import pytest

import h2.config
import h2.connection
import h2.events
import h2.exceptions

REQUEST_HEADERS = [
    (b":authority", b"example.com"),
    (b":path", b"/"),
    (b":scheme", b"https"),
    (b":method", b"POST"),
]


def _connection() -> h2.connection.H2Connection:
    connection = h2.connection.H2Connection()
    connection.initiate_connection()
    return connection


def _pair() -> tuple[h2.connection.H2Connection, h2.connection.H2Connection]:
    client = h2.connection.H2Connection()
    client.initiate_connection()
    server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))
    server.initiate_connection()
    server.receive_data(client.data_to_send())
    return client, server


def test_request_content_length_rejects_end_stream_on_trailers() -> None:
    client, server = _pair()
    client.send_headers(1, REQUEST_HEADERS + [(b"content-length", b"5")])
    server.receive_data(client.data_to_send())

    client.send_headers(1, [(b"x-checksum", b"abc")], end_stream=True)
    with pytest.raises(h2.exceptions.InvalidBodyLengthError):
        server.receive_data(client.data_to_send())


def test_request_content_length_accepts_matching_body_then_trailers() -> None:
    client, server = _pair()
    client.send_headers(1, REQUEST_HEADERS + [(b"content-length", b"5")])
    server.receive_data(client.data_to_send())

    client.send_data(1, b"hello")
    server.receive_data(client.data_to_send())
    client.send_headers(1, [(b"x-checksum", b"abc")], end_stream=True)
    events = server.receive_data(client.data_to_send())

    assert any(isinstance(event, h2.events.StreamEnded) for event in events)


def test_response_content_length_rejects_end_stream_on_headers(frame_factory) -> None:
    connection = _connection()
    connection.send_headers(1, REQUEST_HEADERS, end_stream=True)

    response = frame_factory.build_headers_frame(
        [(b":status", b"200"), (b"content-length", b"5")],
        flags=["END_STREAM"],
    )
    with pytest.raises(h2.exceptions.InvalidBodyLengthError):
        connection.receive_data(response.serialize())


def test_response_without_content_length_accepts_end_stream_on_headers(frame_factory) -> None:
    connection = _connection()
    connection.send_headers(1, REQUEST_HEADERS, end_stream=True)

    response = frame_factory.build_headers_frame(
        [(b":status", b"200")], flags=["END_STREAM"]
    )
    events = connection.receive_data(response.serialize())

    assert any(isinstance(event, h2.events.StreamEnded) for event in events)

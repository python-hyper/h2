"""
Test the RFC 8441 extended connect request support.
"""
from __future__ import annotations

import pytest

import h2.config
import h2.connection
import h2.events
from h2.utilities import utf8_encode_headers


class TestRFC8441:
    """
    Tests that the client supports sending an extended connect request
    and the server supports receiving it.
    """

    headers = [
        (":authority", "example.com"),
        (":path", "/"),
        (":scheme", "https"),
        (":method", "CONNECT"),
        (":protocol", "websocket"),
        ("user-agent", "someua/0.0.1"),
    ]

    headers_bytes = [
        (b":authority", b"example.com"),
        (b":path", b"/"),
        (b":scheme", b"https"),
        (b":method", b"CONNECT"),
        (b":protocol", b"websocket"),
        (b"user-agent", b"someua/0.0.1"),
    ]

    @pytest.mark.parametrize("headers", [headers, headers_bytes])
    def test_can_send_headers(self, frame_factory, headers) -> None:
        client = h2.connection.H2Connection()
        client.initiate_connection()
        client.send_headers(stream_id=1, headers=headers)

        server = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False),
        )
        events = server.receive_data(client.data_to_send())
        event = events[1]
        assert isinstance(event, h2.events.RequestReceived)
        assert event.stream_id == 1
        assert event.headers == utf8_encode_headers(headers)

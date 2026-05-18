"""
This module contains tests that use invalid content lengths, and validates that
they fail appropriately.
"""
from __future__ import annotations

import pytest

import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions


class TestInvalidContentLengths:
    """
    Hyper-h2 raises Protocol Errors when the content-length sent by a remote
    peer is not valid.
    """

    example_request_headers_without_content_length = [
        (":authority", "example.com"),
        (":path", "/"),
        (":scheme", "https"),
        (":method", "POST"),
    ]
    example_request_headers = [
        *example_request_headers_without_content_length,
        ("content-length", "15"),
    ]
    example_request_headers_bytes_without_content_length = [
        (b":authority", b"example.com"),
        (b":path", b"/"),
        (b":scheme", b"https"),
        (b":method", b"POST"),
    ]
    example_request_headers_bytes = [
        *example_request_headers_bytes_without_content_length,
        (b"content-length", b"15"),
    ]
    example_response_headers = [
        (":status", "200"),
        ("server", "fake-serv/0.1.0"),
    ]
    server_config = h2.config.H2Configuration(client_side=False)

    @pytest.mark.parametrize(
        "request_headers",
        [
            example_request_headers_without_content_length,
            example_request_headers_bytes_without_content_length,
        ],
    )
    def test_duplicate_matching_content_lengths(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending duplicate matching content-length fields are
        accepted.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        headers = frame_factory.build_headers_frame(
            headers=[
                *request_headers,
                ("content-length", "15"),
                ("content-length", "15"),
            ],
        )
        data = frame_factory.build_data_frame(
            data=b"\x01"*15,
            flags=["END_STREAM"],
        )

        events = c.receive_data(headers.serialize() + data.serialize())

        assert isinstance(events[0], h2.events.RequestReceived)
        assert isinstance(events[1], h2.events.DataReceived)
        assert isinstance(events[2], h2.events.StreamEnded)
        assert c.data_to_send() == b""

    @pytest.mark.parametrize(
        "request_headers",
        [
            example_request_headers_without_content_length,
            example_request_headers_bytes_without_content_length,
        ],
    )
    def test_duplicate_conflicting_content_lengths(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending duplicate conflicting content-length fields cause
        Protocol Errors.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        headers = frame_factory.build_headers_frame(
            headers=[
                *request_headers,
                ("content-length", "15"),
                ("content-length", "16"),
            ],
        )
        with pytest.raises(
            h2.exceptions.ProtocolError,
            match="Conflicting content-length headers: 15 and 16",
        ):
            c.receive_data(headers.serialize())

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_too_much_data(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending data in excess of content-length causes Protocol
        Errors.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        headers = frame_factory.build_headers_frame(
            headers=request_headers,
        )
        first_data = frame_factory.build_data_frame(data=b"\x01"*15)
        c.receive_data(headers.serialize() + first_data.serialize())
        c.clear_outbound_data_buffer()

        second_data = frame_factory.build_data_frame(data=b"\x01")
        with pytest.raises(h2.exceptions.InvalidBodyLengthError) as exp:
            c.receive_data(second_data.serialize())

        assert exp.value.expected_length == 15
        assert exp.value.actual_length == 16
        assert str(exp.value) == (
            "InvalidBodyLengthError: Expected 15 bytes, received 16"
        )

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_insufficient_data(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending less data than content-length causes Protocol
        Errors.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        headers = frame_factory.build_headers_frame(
            headers=request_headers,
        )
        first_data = frame_factory.build_data_frame(data=b"\x01"*13)
        c.receive_data(headers.serialize() + first_data.serialize())
        c.clear_outbound_data_buffer()

        second_data = frame_factory.build_data_frame(
            data=b"\x01",
            flags=["END_STREAM"],
        )
        with pytest.raises(h2.exceptions.InvalidBodyLengthError) as exp:
            c.receive_data(second_data.serialize())

        assert exp.value.expected_length == 15
        assert exp.value.actual_length == 14
        assert str(exp.value) == (
            "InvalidBodyLengthError: Expected 15 bytes, received 14"
        )

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_insufficient_data_empty_frame(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending less data than content-length where the last data
        frame is empty causes Protocol Errors.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        headers = frame_factory.build_headers_frame(
            headers=request_headers,
        )
        first_data = frame_factory.build_data_frame(data=b"\x01"*14)
        c.receive_data(headers.serialize() + first_data.serialize())
        c.clear_outbound_data_buffer()

        second_data = frame_factory.build_data_frame(
            data=b"",
            flags=["END_STREAM"],
        )
        with pytest.raises(h2.exceptions.InvalidBodyLengthError) as exp:
            c.receive_data(second_data.serialize())

        assert exp.value.expected_length == 15
        assert exp.value.actual_length == 14
        assert str(exp.value) == (
            "InvalidBodyLengthError: Expected 15 bytes, received 14"
        )

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

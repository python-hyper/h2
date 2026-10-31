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
        "value", [
            "15a", "15.0", "-15", "+15", " 15", "15 ", "1e2", "0xF", "15_000", "15,000", "NaN", "\x00", "0b1111", "0o17",
            ("1" * 5000), # https://docs.python.org/3/library/stdtypes.html#int-max-str-digits
        ],
    )
    def test_content_length_with_non_digit_value(self, frame_factory, value) -> None:
        """
        Remote peers sending content-length with non-digit value causes Protocol
        Errors.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        headers = frame_factory.build_headers_frame(
            headers=[
                *self.example_request_headers_bytes_without_content_length,
                ("content-length", value),
            ],
        )
        with pytest.raises(
            h2.exceptions.ProtocolError,
            match=f"Invalid content-length header",
        ):
            c.receive_data(headers.serialize())

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

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


class TestContentLengthEnforcedAtTrailers:
    """
    RFC 9113 § 8.1.1: a request or response is malformed if the value of a
    content-length header field does not equal the sum of the DATA frame
    payload lengths that form the content. The listed exemptions are 204, 304
    and HEAD, none of which is a trailers section, so a stream that ends with
    trailers must still have its body length policed.

    A trailers section may not carry a content-length header field at all, so
    it can never redefine the expected length either.
    """

    example_request_headers = [
        (":authority", "example.com"),
        (":path", "/"),
        (":scheme", "https"),
        (":method", "POST"),
        ("content-length", "15"),
    ]
    server_config = h2.config.H2Configuration(client_side=False)

    def _server(self, frame_factory, request_headers) -> h2.connection.H2Connection:
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.receive_data(frame_factory.build_headers_frame(headers=request_headers).serialize())
        return c

    @pytest.mark.parametrize("request_headers", [example_request_headers])
    def test_insufficient_data_ended_by_trailers(self, frame_factory, request_headers) -> None:
        """
        Remote peers sending less data than content-length and then ending the
        stream with trailers causes Protocol Errors.
        """
        c = self._server(frame_factory, request_headers)
        c.receive_data(frame_factory.build_data_frame(data=b"\x01"*13).serialize())
        c.clear_outbound_data_buffer()

        trailers = frame_factory.build_headers_frame(
            headers=[("x-checksum", "0")],
            flags=["END_STREAM"],
        )
        with pytest.raises(h2.exceptions.InvalidBodyLengthError) as exp:
            c.receive_data(trailers.serialize())

        assert exp.value.expected_length == 15
        assert exp.value.actual_length == 13
        assert str(exp.value) == (
            "InvalidBodyLengthError: Expected 15 bytes, received 13"
        )

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_no_data_ended_by_trailers(self, frame_factory) -> None:
        """
        Remote peers sending no data at all for a non-zero content-length and
        then ending the stream with trailers causes Protocol Errors.
        """
        c = self._server(frame_factory, self.example_request_headers)
        c.clear_outbound_data_buffer()

        trailers = frame_factory.build_headers_frame(
            headers=[("x-checksum", "0")],
            flags=["END_STREAM"],
        )
        with pytest.raises(h2.exceptions.InvalidBodyLengthError) as exp:
            c.receive_data(trailers.serialize())

        assert exp.value.expected_length == 15
        assert exp.value.actual_length == 0

    @pytest.mark.parametrize("content_length", ["13", "15", "0", "banana"])
    def test_content_length_rejected_in_trailers(self, frame_factory, content_length) -> None:
        """
        A trailers section must not carry a content-length header field at
        all, whatever the value: RFC 9110 § 6.5.1 keeps fields that describe
        message framing out of trailer sections, because their evaluation is
        necessary before the content is received.
        """
        c = self._server(frame_factory, self.example_request_headers)
        c.receive_data(frame_factory.build_data_frame(data=b"\x01"*15).serialize())
        c.clear_outbound_data_buffer()

        trailers = frame_factory.build_headers_frame(
            headers=[("content-length", content_length), ("x-checksum", "0")],
            flags=["END_STREAM"],
        )
        with pytest.raises(h2.exceptions.ProtocolError) as exp:
            c.receive_data(trailers.serialize())

        assert "content-length header in trailer" in str(exp.value)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_matching_body_ended_by_trailers_is_accepted(self, frame_factory) -> None:
        """
        A trailers section that ends a stream whose body matches content-length
        is still accepted, and emits TrailersReceived.
        """
        c = self._server(frame_factory, self.example_request_headers)
        c.receive_data(frame_factory.build_data_frame(data=b"\x01"*15).serialize())
        c.clear_outbound_data_buffer()

        trailers = frame_factory.build_headers_frame(
            headers=[("x-checksum", "0")],
            flags=["END_STREAM"],
        )
        events = c.receive_data(trailers.serialize())

        assert any(isinstance(e, h2.events.TrailersReceived) for e in events)

    def test_trailers_without_content_length_unchanged(self, frame_factory) -> None:
        """
        A request with no content-length that ends with trailers is unaffected
        by trailers-time validation.
        """
        headers = [
            (":authority", "example.com"),
            (":path", "/"),
            (":scheme", "https"),
            (":method", "POST"),
        ]
        c = self._server(frame_factory, headers)
        c.receive_data(frame_factory.build_data_frame(data=b"\x01"*3).serialize())
        c.clear_outbound_data_buffer()

        trailers = frame_factory.build_headers_frame(
            headers=[("x-checksum", "0")],
            flags=["END_STREAM"],
        )
        events = c.receive_data(trailers.serialize())

        assert any(isinstance(e, h2.events.TrailersReceived) for e in events)

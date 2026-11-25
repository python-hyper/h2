from __future__ import annotations

import pytest

import h2.connection

EXAMPLE_REQUEST_HEADERS_BYTES = [
    (b":authority", b"example.com"),
    (b":path", b"/"),
    (b":scheme", b"https"),
    (b":method", b"HEAD"),
]

EXAMPLE_REQUEST_HEADERS = [
    (":authority", "example.com"),
    (":path", "/"),
    (":scheme", "https"),
    (":method", "HEAD"),
]


class TestHeadRequest:
    example_response_headers = [
        (b":status", b"200"),
        (b"server", b"fake-serv/0.1.0"),
        (b"content_length", b"1"),
    ]

    @pytest.mark.parametrize("headers", [EXAMPLE_REQUEST_HEADERS, EXAMPLE_REQUEST_HEADERS_BYTES])
    def test_non_zero_content_and_no_body(self, frame_factory, headers) -> None:
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, headers, end_stream=True)

        f = frame_factory.build_headers_frame(
            self.example_response_headers,
            flags=["END_STREAM"],
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 2
        event = events[0]

        assert isinstance(event, h2.events.ResponseReceived)
        assert event.stream_id == 1
        assert event.headers == self.example_response_headers

    @pytest.mark.parametrize("headers", [EXAMPLE_REQUEST_HEADERS, EXAMPLE_REQUEST_HEADERS_BYTES])
    def test_reject_non_zero_content_and_body(self, frame_factory, headers) -> None:
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, headers)

        headers = frame_factory.build_headers_frame(
            self.example_response_headers,
        )
        data = frame_factory.build_data_frame(data=b"\x01")

        c.receive_data(headers.serialize())
        with pytest.raises(h2.exceptions.InvalidBodyLengthError):
            c.receive_data(data.serialize())


class TestPushedHeadRequest:
    """Regression test for pushed HEAD responses carrying content-length (#1330)."""

    pushed_response_headers = [
        (b":status", b"200"),
        (b"content-length", b"5"),
    ]

    @staticmethod
    def _receive_pushed_response(frame_factory, method: bytes) -> list[h2.events.Event]:
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(
            1,
            [
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", b"example.com"),
                (b":path", b"/"),
            ],
            end_stream=False,
        )

        pushed_request_headers = [
            (b":method", method),
            (b":scheme", b"https"),
            (b":authority", b"example.com"),
            (b":path", b"/"),
        ]
        push_promise = frame_factory.build_push_promise_frame(
            stream_id=1,
            promised_stream_id=2,
            headers=pushed_request_headers,
            flags=["END_HEADERS"],
        )
        response = frame_factory.build_headers_frame(
            TestPushedHeadRequest.pushed_response_headers,
            stream_id=2,
        )
        data = frame_factory.build_data_frame(
            data=b"",
            flags=["END_STREAM"],
            stream_id=2,
        )
        return c.receive_data(
            push_promise.serialize() + response.serialize() + data.serialize(),
        )

    def test_pushed_head_response_with_content_length_has_no_body(self, frame_factory) -> None:
        events = self._receive_pushed_response(frame_factory, b"HEAD")
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].stream_id == 2
        assert data_events[0].data == b""

    def test_pushed_get_response_with_content_length_rejects_empty_body(self, frame_factory) -> None:
        with pytest.raises(h2.exceptions.InvalidBodyLengthError):
            self._receive_pushed_response(frame_factory, b"GET")

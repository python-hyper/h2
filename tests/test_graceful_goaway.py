"""
Tests for graceful shutdown: a GOAWAY frame with NO_ERROR.

RFC 9113, Section 6.8: the receiver of a GOAWAY must not open new streams, but
"activity on streams numbered lower than or equal to the last stream identifier
might still complete successfully". Servers commonly send GOAWAY(NO_ERROR,
2**31-1), then a PING, then a second GOAWAY with the real last stream ID.
"""
from __future__ import annotations

import pytest

import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions

MAX_STREAM_ID = 2**31 - 1


class TestGracefulGoAwayClient:
    """
    A client receives a graceful GOAWAY while a request is in flight.
    """

    request_headers = [
        (":authority", "example.com"),
        (":path", "/"),
        (":scheme", "https"),
        (":method", "GET"),
    ]
    post_headers = [
        (":authority", "example.com"),
        (":path", "/upload"),
        (":scheme", "https"),
        (":method", "POST"),
    ]
    response_headers = [
        (":status", "200"),
        ("server", "fake-serv/0.1.0"),
    ]

    def client_with_request(
        self, frame_factory, *, end_stream=True,
    ) -> h2.connection.H2Connection:
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(
            1, self.request_headers if end_stream else self.post_headers,
            end_stream=end_stream,
        )
        c.receive_data(frame_factory.build_settings_frame({}).serialize())
        c.clear_outbound_data_buffer()
        return c

    def test_ping_after_graceful_goaway_is_acked(self, frame_factory) -> None:
        """
        GOAWAY(NO_ERROR) followed by PING in the same read does not raise, and
        the PING is acknowledged (this is the two-stage shutdown recommended
        by RFC 9113).
        """
        c = self.client_with_request(frame_factory)
        goaway = frame_factory.build_goaway_frame(last_stream_id=MAX_STREAM_ID)
        ping = frame_factory.build_ping_frame(b"\x01" * 8)

        events = c.receive_data(goaway.serialize() + ping.serialize())

        assert [type(e) for e in events] == [
            h2.events.ConnectionTerminated, h2.events.PingReceived,
        ]
        assert events[0].error_code == h2.errors.ErrorCodes.NO_ERROR
        assert events[0].last_stream_id == MAX_STREAM_ID
        assert c.state_machine.state == h2.connection.ConnectionState.CLOSED
        ack = frame_factory.build_ping_frame(b"\x01" * 8, flags=["ACK"])
        assert c.data_to_send() == ack.serialize()

    def test_in_flight_response_completes(self, frame_factory) -> None:
        """
        A response on a stream at or below last_stream_id is delivered in full
        after a graceful GOAWAY.
        """
        c = self.client_with_request(frame_factory)
        goaway = frame_factory.build_goaway_frame(last_stream_id=1)
        headers = frame_factory.build_headers_frame(self.response_headers)
        data = frame_factory.build_data_frame(b"hello", flags=["END_STREAM"])

        events = c.receive_data(
            goaway.serialize() + headers.serialize() + data.serialize(),
        )

        assert [type(e) for e in events] == [
            h2.events.ConnectionTerminated,
            h2.events.ResponseReceived,
            h2.events.DataReceived,
            h2.events.StreamEnded,
        ]
        assert events[2].data == b"hello"

    def test_outbound_data_is_kept_and_flow_control_continues(self, frame_factory) -> None:
        """
        A graceful GOAWAY does not discard queued outbound frames, and the
        client can still acknowledge received data with WINDOW_UPDATE frames.
        """
        c = self.client_with_request(frame_factory)
        c.ping(b"\x02" * 8)
        queued = c.data_to_send()
        c.ping(b"\x02" * 8)

        goaway = frame_factory.build_goaway_frame(last_stream_id=1)
        headers = frame_factory.build_headers_frame(self.response_headers)
        data = frame_factory.build_data_frame(b"x" * 1000)
        events = c.receive_data(
            goaway.serialize() + headers.serialize() + data.serialize(),
        )
        assert c.data_to_send() == queued

        assert events[-1].flow_controlled_length == 1000
        c.increment_flow_control_window(1000, stream_id=1)
        c.increment_flow_control_window(1000)
        assert c.data_to_send() == (
            frame_factory.build_window_update_frame(
                stream_id=1, increment=1000,
            ).serialize()
            + frame_factory.build_window_update_frame(
                stream_id=0, increment=1000,
            ).serialize()
        )

    def test_client_can_finish_request_body(self, frame_factory) -> None:
        """
        A client can keep sending the body of an in-flight request after a
        graceful GOAWAY.
        """
        c = self.client_with_request(frame_factory, end_stream=False)
        goaway = frame_factory.build_goaway_frame(last_stream_id=1)
        c.receive_data(goaway.serialize())

        c.send_data(1, b"body", end_stream=True)

        expected = frame_factory.build_data_frame(b"body", flags=["END_STREAM"])
        assert c.data_to_send() == expected.serialize()

    def test_cannot_open_new_stream_while_draining(self, frame_factory) -> None:
        """
        Opening a new stream after a graceful GOAWAY raises ProtocolError, but
        the in-flight stream still completes afterwards.
        """
        c = self.client_with_request(frame_factory)
        goaway = frame_factory.build_goaway_frame(last_stream_id=1)
        c.receive_data(goaway.serialize())

        with pytest.raises(h2.exceptions.ProtocolError):
            c.send_headers(3, self.request_headers, end_stream=True)
        assert not c.data_to_send()

        headers = frame_factory.build_headers_frame(
            self.response_headers, flags=["END_STREAM"],
        )
        events = c.receive_data(headers.serialize())
        assert [type(e) for e in events] == [
            h2.events.ResponseReceived, h2.events.StreamEnded,
        ]

    def test_second_graceful_goaway_keeps_draining(self, frame_factory) -> None:
        """
        The two-stage shutdown (GOAWAY with 2**31-1, PING, GOAWAY with the
        real last stream ID) keeps the in-flight stream usable.
        """
        c = self.client_with_request(frame_factory)
        first = frame_factory.build_goaway_frame(last_stream_id=MAX_STREAM_ID)
        ping = frame_factory.build_ping_frame(b"\x03" * 8)
        second = frame_factory.build_goaway_frame(last_stream_id=1)
        headers = frame_factory.build_headers_frame(
            self.response_headers, flags=["END_STREAM"],
        )

        events = c.receive_data(
            first.serialize() + ping.serialize() + second.serialize()
            + headers.serialize(),
        )

        assert [type(e) for e in events] == [
            h2.events.ConnectionTerminated,
            h2.events.PingReceived,
            h2.events.ConnectionTerminated,
            h2.events.ResponseReceived,
            h2.events.StreamEnded,
        ]
        assert events[2].last_stream_id == 1

    def test_reset_after_graceful_goaway(self, frame_factory) -> None:
        """
        The frame sequence from mitmproxy/mitmproxy#5897: the response ends,
        the server resets the stream, sends a graceful GOAWAY and resets the
        stream again. None of this is a connection error.
        """
        c = self.client_with_request(frame_factory)
        frames = [
            frame_factory.build_headers_frame(self.response_headers),
            frame_factory.build_data_frame(b"<!DOCTYPE html>"),
            frame_factory.build_data_frame(b"", flags=["END_STREAM"]),
            frame_factory.build_rst_stream_frame(stream_id=1, error_code=0),
            frame_factory.build_goaway_frame(last_stream_id=MAX_STREAM_ID),
            frame_factory.build_rst_stream_frame(stream_id=1, error_code=5),
        ]

        events = c.receive_data(b"".join(f.serialize() for f in frames))

        assert isinstance(events[-1], h2.events.ConnectionTerminated)
        assert events[-1].error_code == h2.errors.ErrorCodes.NO_ERROR
        assert c.state_machine.state == h2.connection.ConnectionState.CLOSED

    def test_settings_after_graceful_goaway_are_acked(self, frame_factory) -> None:
        """
        SETTINGS frames received while draining are applied and acknowledged.
        """
        c = self.client_with_request(frame_factory)
        goaway = frame_factory.build_goaway_frame(last_stream_id=1)
        settings = frame_factory.build_settings_frame(
            {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 5},
        )

        events = c.receive_data(goaway.serialize() + settings.serialize())

        assert isinstance(events[-1], h2.events.RemoteSettingsChanged)
        assert c.data_to_send() == frame_factory.build_settings_frame(
            {}, ack=True,
        ).serialize()

    def test_error_goaway_ends_draining(self, frame_factory) -> None:
        """
        A GOAWAY with an error code after a graceful one closes the connection
        for good: the outbound buffer is cleared and later frames are ignored.
        """
        c = self.client_with_request(frame_factory)
        graceful = frame_factory.build_goaway_frame(last_stream_id=1)
        error = frame_factory.build_goaway_frame(
            last_stream_id=1, error_code=h2.errors.ErrorCodes.INTERNAL_ERROR,
        )
        c.receive_data(graceful.serialize())
        c.ping(b"\x04" * 8)

        events = c.receive_data(error.serialize())
        assert len(events) == 1
        assert events[0].error_code == h2.errors.ErrorCodes.INTERNAL_ERROR
        assert not c.data_to_send()

        headers = frame_factory.build_headers_frame(
            self.response_headers, flags=["END_STREAM"],
        )
        assert c.receive_data(headers.serialize()) == []

    def test_local_close_ends_draining(self, frame_factory) -> None:
        """
        Calling close_connection() while draining sends GOAWAY and closes the
        connection for good; later frames are ignored.
        """
        c = self.client_with_request(frame_factory)
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=1).serialize())

        c.close_connection()
        assert c.data_to_send() == frame_factory.build_goaway_frame(
            last_stream_id=0,
        ).serialize()

        ping = frame_factory.build_ping_frame(b"\x05" * 8)
        assert c.receive_data(ping.serialize()) == []
        assert not c.data_to_send()

    def test_non_graceful_goaway_clears_outbound_data(self, frame_factory) -> None:
        """
        A GOAWAY with an error code keeps its existing behaviour: the outbound
        buffer is cleared and in-flight streams get no further frames.
        """
        c = self.client_with_request(frame_factory)
        c.ping(b"\x06" * 8)
        goaway = frame_factory.build_goaway_frame(
            last_stream_id=1, error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        headers = frame_factory.build_headers_frame(
            self.response_headers, flags=["END_STREAM"],
        )

        events = c.receive_data(goaway.serialize() + headers.serialize())

        assert [type(e) for e in events] == [h2.events.ConnectionTerminated]
        assert not c.data_to_send()


class TestGracefulGoAwayServer:
    """
    A server receives a graceful GOAWAY from the client while it is still
    answering a request.
    """

    request_headers = [
        (":authority", "example.com"),
        (":path", "/"),
        (":scheme", "https"),
        (":method", "GET"),
    ]
    response_headers = [
        (":status", "200"),
        ("server", "fake-serv/0.1.0"),
    ]
    server_config = h2.config.H2Configuration(client_side=False)

    def test_server_can_finish_response(self, frame_factory) -> None:
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.receive_data(frame_factory.build_headers_frame(
            self.request_headers, flags=["END_STREAM"],
        ).serialize())
        c.clear_outbound_data_buffer()

        events = c.receive_data(
            frame_factory.build_goaway_frame(last_stream_id=0).serialize(),
        )
        assert isinstance(events[0], h2.events.ConnectionTerminated)

        c.send_headers(1, self.response_headers)
        c.send_data(1, b"done", end_stream=True)

        frame_factory.refresh_encoder()
        expected = (
            frame_factory.build_headers_frame(self.response_headers).serialize()
            + frame_factory.build_data_frame(b"done", flags=["END_STREAM"]).serialize()
        )
        assert c.data_to_send() == expected


class TestGracefulGoAwayEdges:
    """
    A graceful GOAWAY must not revive a closed connection, must not let local
    code open streams by other routes, and must keep the client and server
    rules of the open connection.
    """

    request_headers = TestGracefulGoAwayClient.request_headers
    response_headers = TestGracefulGoAwayClient.response_headers
    server_config = h2.config.H2Configuration(client_side=False)

    def client_with_request(self, frame_factory) -> h2.connection.H2Connection:
        return TestGracefulGoAwayClient().client_with_request(frame_factory)

    def assert_terminal(self, c, frame_factory) -> None:
        graceful = frame_factory.build_goaway_frame(last_stream_id=1)
        ping = frame_factory.build_ping_frame(b"\x07" * 8)
        events = c.receive_data(graceful.serialize() + ping.serialize())
        assert [type(e) for e in events] == [h2.events.ConnectionTerminated]
        assert not c.state_machine.draining
        assert not c.data_to_send()

    def test_graceful_goaway_after_local_close_stays_closed(self, frame_factory) -> None:
        c = self.client_with_request(frame_factory)
        c.close_connection()
        c.clear_outbound_data_buffer()
        self.assert_terminal(c, frame_factory)

    def test_graceful_goaway_after_error_goaway_stays_closed(self, frame_factory) -> None:
        c = self.client_with_request(frame_factory)
        c.receive_data(frame_factory.build_goaway_frame(
            last_stream_id=1, error_code=h2.errors.ErrorCodes.INTERNAL_ERROR,
        ).serialize())
        self.assert_terminal(c, frame_factory)

    def test_graceful_goaway_after_protocol_error_stays_closed(self, frame_factory) -> None:
        c = self.client_with_request(frame_factory)
        # DATA on an idle stream is a connection error.
        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(frame_factory.build_data_frame(b"x", stream_id=7).serialize())
        c.clear_outbound_data_buffer()
        self.assert_terminal(c, frame_factory)

    def test_push_stream_refused_while_draining(self, frame_factory) -> None:
        """
        A server that received a graceful GOAWAY cannot push, and the refusal
        does not end the drain: the response can still be sent.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.receive_data(frame_factory.build_headers_frame(
            self.request_headers, flags=["END_STREAM"],
        ).serialize())
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=0).serialize())
        c.clear_outbound_data_buffer()

        with pytest.raises(h2.exceptions.ProtocolError):
            c.push_stream(1, 2, self.request_headers)
        assert c.state_machine.draining
        assert not c.data_to_send()

        c.send_headers(1, self.response_headers, end_stream=True)
        assert c.data_to_send()

    def test_upgrade_refused_while_draining(self, frame_factory) -> None:
        c = h2.connection.H2Connection()
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=0).serialize())
        assert c.state_machine.draining

        with pytest.raises(h2.exceptions.ProtocolError):
            c.initiate_upgrade_connection()
        assert not c.data_to_send()
        assert 1 not in c.streams

    def test_push_promise_received_while_draining(self, frame_factory) -> None:
        """
        The sender of a GOAWAY may still push on an open request; only the
        receiver may not open streams.
        """
        c = self.client_with_request(frame_factory)
        frames = [
            frame_factory.build_goaway_frame(last_stream_id=1),
            frame_factory.build_push_promise_frame(
                stream_id=1, promised_stream_id=2, headers=self.request_headers,
                flags=["END_HEADERS"],
            ),
            frame_factory.build_headers_frame(
                self.response_headers, flags=["END_STREAM"],
            ),
        ]

        events = c.receive_data(b"".join(f.serialize() for f in frames))

        assert [type(e) for e in events] == [
            h2.events.ConnectionTerminated,
            h2.events.PushedStreamReceived,
            h2.events.ResponseReceived,
            h2.events.StreamEnded,
        ]
        assert c.state_machine.draining

    def test_role_rules_still_apply_while_draining(self, frame_factory) -> None:
        """
        A client may not send ALTSVC frames. Draining does not change that.
        """
        c = self.client_with_request(frame_factory)
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=1).serialize())

        with pytest.raises(h2.exceptions.ProtocolError):
            c.advertise_alternative_service(b'h2=":8000"', origin=b"example.com")
        assert not c.data_to_send()

    def test_server_rules_still_apply_while_draining(self, frame_factory) -> None:
        """
        A server may not receive PUSH_PROMISE, draining or not.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.receive_data(frame_factory.build_headers_frame(self.request_headers).serialize())
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=0).serialize())

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(frame_factory.build_push_promise_frame(
                stream_id=1, promised_stream_id=2, headers=self.request_headers,
                flags=["END_HEADERS"],
            ).serialize())
        assert not c.state_machine.draining

    def test_peer_stream_after_graceful_goaway_from_idle(self, frame_factory) -> None:
        """
        A server that receives a graceful GOAWAY before any stream may still
        serve a stream the client opens afterwards: only the GOAWAY receiver
        is barred from opening streams. The drain tracks the open state, so
        the response can be sent.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.receive_data(frame_factory.build_goaway_frame(last_stream_id=0).serialize())
        assert c.state_machine.draining

        events = c.receive_data(
            frame_factory.build_headers_frame(self.request_headers).serialize()
            + frame_factory.build_data_frame(b"x", flags=["END_STREAM"]).serialize(),
        )
        assert [type(e) for e in events] == [
            h2.events.RequestReceived, h2.events.DataReceived, h2.events.StreamEnded,
        ]
        c.clear_outbound_data_buffer()

        c.send_headers(1, self.response_headers)
        c.send_data(1, b"ok", end_stream=True)
        assert c.data_to_send()
        assert c.state_machine.draining

# -*- coding: utf-8 -*-
"""
test_closed_streams
~~~~~~~~~~~~~~~~~~~

Tests that we handle closed streams correctly.
"""
import pytest

import h2.connection
import h2.errors
import h2.events
import h2.exceptions


class TestClosedStreams(object):
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]

    def test_can_receive_multiple_rst_stream_frames(self, frame_factory):
        """
        Multiple RST_STREAM frames can be received, either at once or well
        after one another. Only the first fires an event.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)

        f = frame_factory.build_rst_stream_frame(stream_id=1)
        events = c.receive_data(f.serialize() * 3)
        events += c.receive_data(f.serialize() * 3)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.StreamReset)

    def test_closed_stream_resets_further_frames(self, frame_factory):
        """
        A stream that is closed can receive further frames: it simply sends
        RST_STREAM for it.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.initiate_connection()

        f = frame_factory.build_headers_frame(self.example_request_headers)
        c.receive_data(f.serialize())
        c.reset_stream(1)
        c.clear_outbound_data_buffer()

        f = frame_factory.build_data_frame(b'hi there')
        events = c.receive_data(f.serialize())

        f = frame_factory.build_rst_stream_frame(1, h2.errors.STREAM_CLOSED)
        assert not events
        assert c.data_to_send() == f.serialize()

        events = c.receive_data(f.serialize() * 3)
        assert not events
        assert c.data_to_send() == f.serialize() * 3

    def test_receiving_low_stream_id_causes_goaway(self, frame_factory):
        """
        The remote peer creating a stream with a lower ID than one we've seen
        causes a GOAWAY frame.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.initiate_connection()

        f = frame_factory.build_headers_frame(
            self.example_request_headers,
            stream_id=3,
        )
        c.receive_data(f.serialize())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            self.example_request_headers,
            stream_id=1,
        )

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(f.serialize())

        f = frame_factory.build_goaway_frame(
            last_stream_id=3,
            error_code=h2.errors.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == f.serialize()

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
    example_response_headers = [
        (':status', '200'),
        ('server', 'fake-serv/0.1.0')
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

        # Force an iteration over all the streams to remove them.
        c.open_outbound_streams

        # Receive more data.
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

        f = frame_factory.build_headers_frame(
            self.example_request_headers, flags=['END_STREAM']
        )
        c.receive_data(f.serialize())
        c.send_headers(
            stream_id=1,
            headers=self.example_response_headers,
            end_stream=True
        )
        c.clear_outbound_data_buffer()

        data_frame = frame_factory.build_data_frame(b'hi there')
        events = c.receive_data(data_frame.serialize())

        rst_frame = frame_factory.build_rst_stream_frame(
            1, h2.errors.ErrorCodes.STREAM_CLOSED
        )
        assert not events
        assert c.data_to_send() == rst_frame.serialize()

        events = c.receive_data(data_frame.serialize() * 3)
        assert not events
        assert c.data_to_send() == rst_frame.serialize() * 3

        # Iterate over the streams to make sure it's gone, then confirm the
        # behaviour is unchanged.
        c.open_outbound_streams

        events = c.receive_data(data_frame.serialize() * 3)
        assert not events
        assert c.data_to_send() == rst_frame.serialize() * 3

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

        with pytest.raises(h2.exceptions.StreamIDTooLowError) as e:
            c.receive_data(f.serialize())

        assert e.value.stream_id == 1
        assert e.value.max_stream_id == 3

        f = frame_factory.build_goaway_frame(
            last_stream_id=3,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == f.serialize()

    def test_closed_stream_not_present_in_streams_dict(self, frame_factory):
        """
        When streams have been closed, they get removed from the streams
        dictionary the next time we count the open streams.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.initiate_connection()

        f = frame_factory.build_headers_frame(self.example_request_headers)
        c.receive_data(f.serialize())
        c.push_stream(1, 2, self.example_request_headers)
        c.reset_stream(1)
        c.clear_outbound_data_buffer()

        f = frame_factory.build_rst_stream_frame(stream_id=2)
        c.receive_data(f.serialize())

        # Force a count of the streams.
        assert not c.open_outbound_streams

        # The streams dictionary should be empty.
        assert not c.streams

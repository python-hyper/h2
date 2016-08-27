# -*- coding: utf-8 -*-
"""
test_stream_reset
~~~~~~~~~~~~~~~~~

More complex tests that exercise stream resetting functionality to validate
that connection state is appropriately maintained.

Specifically, these tests validate that streams that have been reset accurately
keep track of connection-level state.
"""
import pytest

import h2.connection
import h2.errors
import h2.events


class TestStreamReset(object):
    """
    Tests for resetting streams.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]
    example_response_headers = [
        (':status', '200'),
        ('server', 'fake-serv/0.1.0'),
        ('content-length', '0')
    ]

    def test_reset_stream_keeps_header_state_correct(self, frame_factory):
        """
        A stream that has been reset still affects the header decoder.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)
        c.reset_stream(stream_id=1)
        c.send_headers(stream_id=3, headers=self.example_request_headers)
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers, stream_id=1
        )
        events = c.receive_data(f.serialize())
        assert not events
        assert not c.data_to_send()

        # This works because the header state should be intact from the headers
        # frame that was send on stream 1, so they should decode cleanly.
        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers, stream_id=3
        )
        event = c.receive_data(f.serialize())[0]

        assert isinstance(event, h2.events.ResponseReceived)
        assert event.stream_id == 3
        assert event.headers == self.example_response_headers

    @pytest.mark.parametrize('close_id,other_id', [(1, 3), (3, 1)])
    def test_reset_stream_keeps_flow_control_correct(self,
                                                     close_id,
                                                     other_id,
                                                     frame_factory):
        """
        A stream that has been reset still affects the connection flow control
        window.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)
        c.send_headers(stream_id=3, headers=self.example_request_headers)

        # Record the initial window size.
        initial_window = c.remote_flow_control_window(stream_id=other_id)

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers, stream_id=close_id
        )
        c.receive_data(f.serialize())
        c.reset_stream(stream_id=close_id)
        c.clear_outbound_data_buffer()

        f = frame_factory.build_data_frame(
            data=b'some data!',
            stream_id=close_id
        )
        events = c.receive_data(f.serialize())
        assert not events
        assert not c.data_to_send()

        new_window = c.remote_flow_control_window(stream_id=other_id)
        assert initial_window - len(b'some data!') == new_window

    def test_reset_stream_automatically_resets_pushed_streams(self,
                                                              frame_factory):
        """
        Resetting a stream causes RST_STREAM frames to be automatically emitted
        to close any streams pushed after the reset.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)
        c.reset_stream(stream_id=1)
        c.clear_outbound_data_buffer()

        f = frame_factory.build_push_promise_frame(
            stream_id=1,
            promised_stream_id=2,
            headers=self.example_request_headers,
        )
        events = c.receive_data(f.serialize())
        assert not events

        f = frame_factory.build_rst_stream_frame(
            stream_id=2,
            error_code=h2.errors.ErrorCodes.REFUSED_STREAM,
        )
        assert c.data_to_send() == f.serialize()

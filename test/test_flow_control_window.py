# -*- coding: utf-8 -*-
"""
test_flow_control
~~~~~~~~~~~~~~~~~

Tests of the flow control management in h2
"""
import pytest

import h2.connection
import h2.errors
import h2.events
import h2.exceptions

from hyperframe.frame import SettingsFrame


class TestFlowControl(object):
    """
    Tests of the flow control management in the connection objects.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]

    DEFAULT_FLOW_WINDOW = 65535

    def test_flow_control_initializes_properly(self):
        """
        The flow control window for a stream should initially be the default
        flow control value.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)

        assert c.local_flow_control_window(1) == self.DEFAULT_FLOW_WINDOW
        assert c.remote_flow_control_window(1) == self.DEFAULT_FLOW_WINDOW

    def test_flow_control_decreases_with_sent_data(self):
        """
        When data is sent on a stream, the flow control window should drop.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.send_data(1, b'some data')

        remaining_length = self.DEFAULT_FLOW_WINDOW - len(b'some data')
        assert (c.local_flow_control_window(1) == remaining_length)

    def test_flow_control_decreases_with_received_data(self, frame_factory):
        """
        When data is received on a stream, the remote flow control window
        should drop.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        f1 = frame_factory.build_headers_frame(self.example_request_headers)
        f2 = frame_factory.build_data_frame(b'some data')

        c.receive_data(f1.serialize() + f2.serialize())

        remaining_length = self.DEFAULT_FLOW_WINDOW - len(b'some data')
        assert (c.remote_flow_control_window(1) == remaining_length)

    def test_flow_control_is_limited_by_connection(self):
        """
        The flow control window is limited by the flow control of the
        connection.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.send_data(1, b'some data')
        c.send_headers(2, self.example_request_headers)

        remaining_length = self.DEFAULT_FLOW_WINDOW - len(b'some data')
        assert (c.local_flow_control_window(2) == remaining_length)

    def test_remote_flow_control_is_limited_by_connection(self, frame_factory):
        """
        The remote flow control window is limited by the flow control of the
        connection.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        f1 = frame_factory.build_headers_frame(self.example_request_headers)
        f2 = frame_factory.build_data_frame(b'some data')
        f3 = frame_factory.build_headers_frame(
            self.example_request_headers,
            stream_id=2,
        )
        c.receive_data(f1.serialize() + f2.serialize() + f3.serialize())

        remaining_length = self.DEFAULT_FLOW_WINDOW - len(b'some data')
        assert (c.remote_flow_control_window(2) == remaining_length)

    def test_cannot_send_more_data_than_window(self):
        """
        Sending more data than the remaining flow control window raises a
        FlowControlError.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.outbound_flow_control_window = 5

        with pytest.raises(h2.exceptions.FlowControlError):
            c.send_data(1, b'some data')

    def test_increasing_connection_window_allows_sending(self, frame_factory):
        """
        Confirm that sending a WindowUpdate frame on the connection frees
        up space for further frames.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.outbound_flow_control_window = 5

        with pytest.raises(h2.exceptions.FlowControlError):
            c.send_data(1, b'some data')

        f = frame_factory.build_window_update_frame(
            stream_id=0,
            increment=5,
        )
        c.receive_data(f.serialize())

        c.clear_outbound_data_buffer()
        c.send_data(1, b'some data')
        assert c.data_to_send()

    def test_increasing_stream_window_allows_sending(self, frame_factory):
        """
        Confirm that sending a WindowUpdate frame on the connection frees
        up space for further frames.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.get_stream_by_id(1).outbound_flow_control_window = 5

        with pytest.raises(h2.exceptions.FlowControlError):
            c.send_data(1, b'some data')

        f = frame_factory.build_window_update_frame(
            stream_id=1,
            increment=5,
        )
        c.receive_data(f.serialize())

        c.clear_outbound_data_buffer()
        c.send_data(1, b'some data')
        assert c.data_to_send()

    def test_flow_control_shrinks_in_response_to_settings(self, frame_factory):
        """
        Acknowledging SETTINGS_INITIAL_WINDOW_SIZE shrinks the flow control
        window.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)

        assert c.local_flow_control_window(1) == 65535

        f = frame_factory.build_settings_frame(
            settings={SettingsFrame.INITIAL_WINDOW_SIZE: 1280}
        )
        events = c.receive_data(f.serialize())
        c.acknowledge_settings(events[0])

        assert c.local_flow_control_window(1) == 1280

    def test_flow_control_grows_in_response_to_settings(self, frame_factory):
        """
        Acknowledging SETTINGS_INITIAL_WINDOW_SIZE grows the flow control
        window.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)

        assert c.local_flow_control_window(1) == 65535

        f = frame_factory.build_settings_frame(
            settings={SettingsFrame.INITIAL_WINDOW_SIZE: 128000}
        )
        events = c.receive_data(f.serialize())
        c.acknowledge_settings(events[0])

        assert c.local_flow_control_window(1) == 128000

    def test_new_streams_have_flow_control_per_settings(self, frame_factory):
        """
        After a SETTINGS_INITIAL_WINDOW_SIZE change is received, new streams
        have appropriate new flow control windows.
        """
        c = h2.connection.H2Connection()

        f = frame_factory.build_settings_frame(
            settings={SettingsFrame.INITIAL_WINDOW_SIZE: 128000}
        )
        events = c.receive_data(f.serialize())
        c.acknowledge_settings(events[0])

        c.send_headers(1, self.example_request_headers)
        assert c.local_flow_control_window(1) == 128000

    def test_window_update_no_stream(self, frame_factory):
        """
        WindowUpdate frames received without streams fire an appropriate
        WindowUpdated event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_window_update_frame(
            stream_id=0,
            increment=5
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.WindowUpdated)
        assert event.stream_id == 0
        assert event.delta == 5

    def test_window_update_with_stream(self, frame_factory):
        """
        WindowUpdate frames received with streams fire an appropriate
        WindowUpdated event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f1 = frame_factory.build_headers_frame(self.example_request_headers)
        f2 = frame_factory.build_window_update_frame(
            stream_id=1,
            increment=66
        )
        data = b''.join(map(lambda f: f.serialize(), [f1, f2]))
        events = c.receive_data(data)

        assert len(events) == 2
        event = events[1]

        assert isinstance(event, h2.events.WindowUpdated)
        assert event.stream_id == 1
        assert event.delta == 66

    def test_we_can_increment_stream_flow_control(self, frame_factory):
        """
        It is possible for the user to increase the flow control window for
        streams.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)
        c.clear_outbound_data_buffer()

        expected_frame = frame_factory.build_window_update_frame(
            stream_id=1,
            increment=5
        )

        events = c.increment_flow_control_window(increment=5, stream_id=1)
        assert not events
        assert c.data_to_send() == expected_frame.serialize()

    def test_we_can_increment_connection_flow_control(self, frame_factory):
        """
        It is possible for the user to increase the flow control window for
        the entire connection.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)
        c.clear_outbound_data_buffer()

        expected_frame = frame_factory.build_window_update_frame(
            stream_id=0,
            increment=5
        )

        events = c.increment_flow_control_window(increment=5)
        assert not events
        assert c.data_to_send() == expected_frame.serialize()

    def test_we_enforce_our_flow_control_window(self, frame_factory):
        """
        The user can set a low flow control window, which leads to connection
        teardown if violated.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        # Change the flow control window to 80 bytes.
        c.update_settings(
            {SettingsFrame.INITIAL_WINDOW_SIZE: 80}
        )
        f = frame_factory.build_settings_frame({}, ack=True)
        c.receive_data(f.serialize())

        # Receive a new stream.
        f = frame_factory.build_headers_frame(self.example_request_headers)
        c.receive_data(f.serialize())

        # Attempt to violate the flow control window.
        c.clear_outbound_data_buffer()
        f = frame_factory.build_data_frame(b'\x01' * 100)

        with pytest.raises(h2.exceptions.FlowControlError):
            c.receive_data(f.serialize())

        # Verify we tear down appropriately.
        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1,
            error_code=h2.errors.FLOW_CONTROL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_shrink_remote_flow_control_settings(self, frame_factory):
        """
        The remote peer acknowledging our SETTINGS_INITIAL_WINDOW_SIZE shrinks
        the flow control window.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)

        assert c.remote_flow_control_window(1) == 65535

        c.update_settings({SettingsFrame.INITIAL_WINDOW_SIZE: 1280})

        f = frame_factory.build_settings_frame({}, ack=True)
        c.receive_data(f.serialize())

        assert c.remote_flow_control_window(1) == 1280

    def test_grow_remote_flow_control_settings(self, frame_factory):
        """
        The remote peer acknowledging our SETTINGS_INITIAL_WINDOW_SIZE grows
        the flow control window.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)

        assert c.remote_flow_control_window(1) == 65535

        c.update_settings({SettingsFrame.INITIAL_WINDOW_SIZE: 128000})
        f = frame_factory.build_settings_frame({}, ack=True)
        c.receive_data(f.serialize())

        assert c.remote_flow_control_window(1) == 128000

    def test_new_streams_have_remote_flow_control(self, frame_factory):
        """
        After a SETTINGS_INITIAL_WINDOW_SIZE change is acknowledged by the
        remote peer, new streams have appropriate new flow control windows.
        """
        c = h2.connection.H2Connection()

        c.update_settings({SettingsFrame.INITIAL_WINDOW_SIZE: 128000})
        f = frame_factory.build_settings_frame({}, ack=True)
        c.receive_data(f.serialize())

        c.send_headers(1, self.example_request_headers)
        assert c.remote_flow_control_window(1) == 128000

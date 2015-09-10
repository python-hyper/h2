# -*- coding: utf-8 -*-
"""
test_basic_logic
~~~~~~~~~~~~~~~~

Test the basic logic of the h2 state machines.
"""
import pytest

import h2.connection
import h2.events
import h2.exceptions

import helpers


class TestBasicClient(object):
    """
    Basic client-side tests.
    """
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

    def test_begin_connection(self, frame_factory):
        """
        Client connections emit the HTTP/2 preamble.
        """
        c = h2.connection.H2Connection()
        expected_settings = frame_factory.build_settings_frame(
            c.local_settings
        )
        expected_data = (
            b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n' + expected_settings.serialize()
        )

        events = c.initiate_connection()
        assert not events
        assert c.data_to_send == expected_data

    def test_sending_headers(self):
        """
        Single headers frames are correctly encoded.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()

        # Clear the data, then send headers.
        c.data_to_send = b''
        events = c.send_headers(1, self.example_request_headers)
        assert not events
        assert c.data_to_send == (
            b'\x00\x00\r\x01\x04\x00\x00\x00\x01'
            b'A\x88/\x91\xd3]\x05\\\x87\xa7\x84\x87\x82'
        )

    def test_sending_data(self):
        """
        Single data frames are encoded correctly.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers)

        # Clear the data, then send some data.
        c.data_to_send = b''
        events = c.send_data(1, b'some data')
        assert not events
        assert c.data_to_send == b'\x00\x00\t\x00\x00\x00\x00\x00\x01some data'

    def test_receiving_a_response(self, frame_factory):
        """
        When receiving a response, the ResponseReceived event fires.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)

        # Clear the data
        c.data_to_send = b''
        f = frame_factory.build_headers_frame(
            self.example_response_headers
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.ResponseReceived)
        assert event.stream_id == 1
        assert event.headers == self.example_response_headers


class TestBasicServer(object):
    """
    Basic server-side tests.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]
    example_response_headers = [
        (':status', '200'),
        ('server', 'hyper-h2/0.1.0')
    ]

    def test_ignores_preamble(self):
        """
        The preamble does not cause any events or frames to be written.
        """
        c = h2.connection.H2Connection(client_side=False)
        preamble = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'

        events = c.receive_data(preamble)
        assert not events
        assert not c.data_to_send

    @pytest.mark.parametrize("chunk_size", range(1, 24))
    def test_drip_feed_preamble(self, chunk_size):
        """
        The preamble can be sent in in less than a single buffer.
        """
        c = h2.connection.H2Connection(client_side=False)
        preamble = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
        events = []

        for i in range(0, len(preamble), chunk_size):
            events += c.receive_data(preamble[i:i+chunk_size])

        assert not events
        assert not c.data_to_send

    def test_no_preamble_errors(self):
        """
        Server side connections require the preamble.
        """
        c = h2.connection.H2Connection(client_side=False)
        encoded_headers_frame = (
            b'\x00\x00\r\x01\x04\x00\x00\x00\x01'
            b'A\x88/\x91\xd3]\x05\\\x87\xa7\x84\x87\x82'
        )

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(encoded_headers_frame)

    def test_initiate_connection_sends_server_preamble(self, frame_factory):
        """
        For server-side connections, initiate_connection sends a server
        preamble.
        """
        c = h2.connection.H2Connection(client_side=False)
        expected_settings = frame_factory.build_settings_frame(
            c.local_settings
        )
        expected_data = expected_settings.serialize()

        events = c.initiate_connection()
        assert not events
        assert c.data_to_send == expected_data

    def test_headers_event(self, frame_factory):
        """
        When a headers frame is received a RequestReceived event fires.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_headers_frame(self.example_request_headers)
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.RequestReceived)
        assert event.stream_id == 1
        assert event.headers == self.example_request_headers

    def test_data_event(self, frame_factory):
        """
        Test that data received on a stream fires a DataReceived event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f1 = frame_factory.build_headers_frame(
            self.example_request_headers, stream_id=3
        )
        f2 = frame_factory.build_data_frame(
            b'some request data',
            stream_id=3,
        )
        data = b''.join(map(lambda f: f.serialize(), [f1, f2]))
        events = c.receive_data(data)

        assert len(events) == 2
        event = events[1]

        assert isinstance(event, h2.events.DataReceived)
        assert event.stream_id == 3
        assert event.data == b'some request data'

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

    def test_receiving_ping_frame(self, frame_factory):
        """
        Ping frames should be immediately ACKed.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        sent_frame = frame_factory.build_ping_frame()
        expected_frame = frame_factory.build_ping_frame(flags=["ACK"])
        expected_data = expected_frame.serialize()

        c.data_to_send = b''
        events = c.receive_data(sent_frame.serialize())

        assert not events
        assert c.data_to_send == expected_data

    def test_receiving_settings_frame_event(self, frame_factory):
        """
        Settings frames should cause a RemoteSettingsChanged event to fire.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_settings_frame(
            settings=helpers.SAMPLE_SETTINGS
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.RemoteSettingsChanged)
        assert len(event.changed_settings) == len(helpers.SAMPLE_SETTINGS)

    def test_acknowledging_settings(self, frame_factory):
        """
        Acknowledging settings causes appropriate Settings frame to be emitted.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        received_frame = frame_factory.build_settings_frame(
            settings=helpers.SAMPLE_SETTINGS
        )
        expected_frame = frame_factory.build_settings_frame(
            settings={}, ack=True
        )
        expected_data = expected_frame.serialize()

        event = c.receive_data(received_frame.serialize())[0]
        c.data_to_send = b''
        events = c.acknowledge_settings(event)

        assert not events
        assert c.data_to_send == expected_data

    def test_settings_ack_is_ignored(self, frame_factory):
        """
        Receiving a SETTINGS ACK should cause no events or data to be emitted.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_settings_frame(
            settings={}, ack=True
        )

        events = c.receive_data(f.serialize())

        assert not events
        assert not c.data_to_send

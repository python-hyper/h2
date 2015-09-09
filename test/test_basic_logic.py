# -*- coding: utf-8 -*-
"""
test_basic_logic
~~~~~~~~~~~~~~~~

Test the basic logic of the h2 state machines.
"""
import pytest

import h2.connection
import h2.exceptions


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

    def test_begin_connection(self):
        """
        Client connections emit the HTTP/2 preamble.
        """
        c = h2.connection.H2Connection()
        events = c.initiate_connection()
        assert not events
        assert c.data_to_send.startswith(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n')

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

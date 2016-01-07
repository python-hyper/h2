# -*- coding: utf-8 -*-
"""
test_invalid_frame_sequences.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This module contains tests that use invalid frame sequences, and validates that
they fail appropriately.
"""
import pytest

import h2.connection
import h2.exceptions


class TestInvalidFrameSequences(object):
    """
    Invalid frame sequences, either sent or received, cause ProtocolErrors to
    be thrown.
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

    def test_cannot_send_on_closed_stream(self):
        """
        When we've closed a stream locally, we cannot send further data.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)

        with pytest.raises(h2.exceptions.ProtocolError):
            c.send_data(1, b'some data')

    def test_missing_preamble_errors(self):
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

    def test_server_connections_reject_even_streams(self, frame_factory):
        """
        Servers do not allow clients to initiate even-numbered streams.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_headers_frame(
            self.example_request_headers, stream_id=2
        )

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(f.serialize())

    def test_clients_reject_odd_stream_pushes(self, frame_factory):
        """
        Clients do not allow servers to push odd numbered streams.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(1, self.example_request_headers, end_stream=True)

        f = frame_factory.build_push_promise_frame(
            stream_id=1,
            headers=self.example_request_headers,
            promised_stream_id=3
        )

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(f.serialize())

# -*- coding: utf-8 -*-
"""
test_header_indexing.py
~~~~~~~~~~~~~~~~~~~~~~~

This module contains tests that use HPACK header tuples that provide additional
metadata to the hpack module about how to encode the headers.
"""
import pytest

from hpack import HeaderTuple, NeverIndexedHeaderTuple

import h2.connection


def assert_header_blocks_actually_equal(block_a, block_b):
    """
    Asserts that two header bocks are really, truly equal, down to the types
    of their tuples. Doesn't return anything.
    """
    assert len(block_a) == len(block_b)

    for a, b in zip(block_a, block_b):
        assert a == b
        assert a.__class__ is b.__class__


class TestHeaderIndexing(object):
    """
    Test that Hyper-h2 can correctly handle never indexed header fields using
    the appropriate hpack data structures.
    """
    example_request_headers = [
        HeaderTuple(u':authority', u'example.com'),
        HeaderTuple(u':path', u'/'),
        HeaderTuple(u':scheme', u'https'),
        HeaderTuple(u':method', u'GET'),
    ]
    bytes_example_request_headers = [
        HeaderTuple(b':authority', b'example.com'),
        HeaderTuple(b':path', b'/'),
        HeaderTuple(b':scheme', b'https'),
        HeaderTuple(b':method', b'GET'),
    ]

    extended_request_headers = [
        HeaderTuple(u':authority', u'example.com'),
        HeaderTuple(u':path', u'/'),
        HeaderTuple(u':scheme', u'https'),
        HeaderTuple(u':method', u'GET'),
        NeverIndexedHeaderTuple(u'authorization', u'realpassword'),
    ]
    bytes_extended_request_headers = [
        HeaderTuple(b':authority', b'example.com'),
        HeaderTuple(b':path', b'/'),
        HeaderTuple(b':scheme', b'https'),
        HeaderTuple(b':method', b'GET'),
        NeverIndexedHeaderTuple(b'authorization', b'realpassword'),
    ]

    example_response_headers = [
        HeaderTuple(u':status', u'200'),
        HeaderTuple(u'server', u'fake-serv/0.1.0')
    ]
    bytes_example_response_headers = [
        HeaderTuple(b':status', b'200'),
        HeaderTuple(b'server', b'fake-serv/0.1.0')
    ]

    extended_response_headers = [
        HeaderTuple(u':status', u'200'),
        HeaderTuple(u'server', u'fake-serv/0.1.0'),
        NeverIndexedHeaderTuple(u'secure', u'you-bet'),
    ]
    bytes_extended_response_headers = [
        HeaderTuple(b':status', b'200'),
        HeaderTuple(b'server', b'fake-serv/0.1.0'),
        NeverIndexedHeaderTuple(b'secure', b'you-bet'),
    ]

    @pytest.mark.parametrize(
        'headers', (
            example_request_headers,
            bytes_example_request_headers,
            extended_request_headers,
            bytes_extended_request_headers,
        )
    )
    def test_sending_header_tuples(self, headers, frame_factory):
        """
        Providing HeaderTuple and HeaderTuple subclasses preserves the metadata
        about indexing.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()

        # Clear the data, then send headers.
        c.clear_outbound_data_buffer()
        c.send_headers(1, headers)

        f = frame_factory.build_headers_frame(headers=headers)
        assert c.data_to_send() == f.serialize()

    @pytest.mark.parametrize(
        'headers', (
            example_request_headers,
            bytes_example_request_headers,
            extended_request_headers,
            bytes_extended_request_headers,
        )
    )
    def test_header_tuples_in_pushes(self, headers, frame_factory):
        """
        Providing HeaderTuple and HeaderTuple subclasses to push promises
        preserves metadata about indexing.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        # We can use normal headers for the request.
        f = frame_factory.build_headers_frame(
            self.example_request_headers
        )
        c.receive_data(f.serialize())

        frame_factory.refresh_encoder()
        expected_frame = frame_factory.build_push_promise_frame(
            stream_id=1,
            promised_stream_id=2,
            headers=headers,
            flags=['END_HEADERS'],
        )

        c.clear_outbound_data_buffer()
        c.push_stream(
            stream_id=1,
            promised_stream_id=2,
            request_headers=headers
        )

        assert c.data_to_send() == expected_frame.serialize()

    @pytest.mark.parametrize(
        'headers,encoding', (
            (example_request_headers, 'utf-8'),
            (bytes_example_request_headers, None),
            (extended_request_headers, 'utf-8'),
            (bytes_extended_request_headers, None),
        )
    )
    def test_header_tuples_are_decoded_request(self,
                                               headers,
                                               encoding,
                                               frame_factory):
        """
        The indexing status of the header is preserved when emitting
        RequestReceived events.
        """
        c = h2.connection.H2Connection(
            client_side=False, header_encoding=encoding
        )
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.RequestReceived)
        assert_header_blocks_actually_equal(headers, event.headers)

    @pytest.mark.parametrize(
        'headers,encoding', (
            (example_response_headers, 'utf-8'),
            (bytes_example_response_headers, None),
            (extended_response_headers, 'utf-8'),
            (bytes_extended_response_headers, None),
        )
    )
    def test_header_tuples_are_decoded_response(self,
                                                headers,
                                                encoding,
                                                frame_factory):
        """
        The indexing status of the header is preserved when emitting
        ResponseReceived events.
        """
        c = h2.connection.H2Connection(header_encoding=encoding)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.ResponseReceived)
        assert_header_blocks_actually_equal(headers, event.headers)

    @pytest.mark.parametrize(
        'headers,encoding', (
            (example_response_headers, 'utf-8'),
            (bytes_example_response_headers, None),
            (extended_response_headers, 'utf-8'),
            (bytes_extended_response_headers, None),
        )
    )
    def test_header_tuples_are_decoded_info_response(self,
                                                     headers,
                                                     encoding,
                                                     frame_factory):
        """
        The indexing status of the header is preserved when emitting
        InformationalResponseReceived events.
        """
        # Manipulate the headers to send 100 Continue. We need to copy the list
        # to avoid breaking the example headers.
        headers = headers[:]
        if encoding:
            headers[0] = HeaderTuple(u':status', u'100')
        else:
            headers[0] = HeaderTuple(b':status', b'100')

        c = h2.connection.H2Connection(header_encoding=encoding)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.InformationalResponseReceived)
        assert_header_blocks_actually_equal(headers, event.headers)

    @pytest.mark.parametrize(
        'headers,encoding', (
            (example_response_headers, 'utf-8'),
            (bytes_example_response_headers, None),
            (extended_response_headers, 'utf-8'),
            (bytes_extended_response_headers, None),
        )
    )
    def test_header_tuples_are_decoded_trailers(self,
                                                headers,
                                                encoding,
                                                frame_factory):
        """
        The indexing status of the header is preserved when emitting
        TrailersReceived events.
        """
        # Manipulate the headers to remove the status, which shouldn't be in
        # the trailers. We need to copy the list to avoid breaking the example
        # headers.
        headers = headers[1:]

        c = h2.connection.H2Connection(header_encoding=encoding)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)
        f = frame_factory.build_headers_frame(self.example_response_headers)
        data = f.serialize()
        c.receive_data(data)

        f = frame_factory.build_headers_frame(headers, flags=['END_STREAM'])
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 2
        event = events[0]

        assert isinstance(event, h2.events.TrailersReceived)
        assert_header_blocks_actually_equal(headers, event.headers)

    @pytest.mark.parametrize(
        'headers,encoding', (
            (example_request_headers, 'utf-8'),
            (bytes_example_request_headers, None),
            (extended_request_headers, 'utf-8'),
            (bytes_extended_request_headers, None),
        )
    )
    def test_header_tuples_are_decoded_push_promise(self,
                                                    headers,
                                                    encoding,
                                                    frame_factory):
        """
        The indexing status of the header is preserved when emitting
        PushedStreamReceived events.
        """
        c = h2.connection.H2Connection(header_encoding=encoding)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f = frame_factory.build_push_promise_frame(
            stream_id=1,
            promised_stream_id=2,
            headers=headers,
            flags=['END_HEADERS'],
        )
        data = f.serialize()
        events = c.receive_data(data)

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.PushedStreamReceived)
        assert_header_blocks_actually_equal(headers, event.headers)

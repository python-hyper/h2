# -*- coding: utf-8 -*-
"""
test_invalid_headers.py
~~~~~~~~~~~~~~~~~~~~~~~

This module contains tests that use invalid header blocks, and validates that
they fail appropriately.
"""
import pytest

import h2.connection
import h2.errors
import h2.events
import h2.exceptions
import h2.utilities

from hypothesis import given
from hypothesis.strategies import binary, lists, tuples

HEADERS_STRATEGY = lists(tuples(binary(), binary()))


class TestInvalidFrameSequences(object):
    """
    Invalid header sequences cause ProtocolErrors to be thrown when received.
    """
    base_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
        ('user-agent', 'someua/0.0.1'),
    ]
    invalid_header_blocks = [
        base_request_headers + [('Uppercase', 'name')],
        base_request_headers + [(':late', 'pseudo-header')],
        [(':path', 'duplicate-pseudo-header')] + base_request_headers,
        base_request_headers + [('connection', 'close')],
        base_request_headers + [('proxy-connection', 'close')],
        base_request_headers + [('keep-alive', 'close')],
        base_request_headers + [('transfer-encoding', 'gzip')],
        base_request_headers + [('upgrade', 'super-protocol/1.1')],
        base_request_headers + [('te', 'chunked')],
    ]

    @pytest.mark.parametrize('headers', invalid_header_blocks)
    def test_headers_event(self, frame_factory, headers):
        """
        Test invalid headers are rejected with PROTOCOL_ERROR.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()

        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(data)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=0, error_code=h2.errors.PROTOCOL_ERROR
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_transfer_encoding_trailers_is_valid(self, frame_factory):
        """
        Transfer-Encoding trailers is allowed by the filter.
        """
        headers = (
            self.base_request_headers + [('te', 'trailers')]
        )

        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()

        events = c.receive_data(data)
        assert len(events) == 1
        request_event = events[0]
        assert request_event.headers == headers


class TestFilter(object):
    """
    Test the filter function directly.

    These tests exists to confirm the behaviour of the filter function in a
    wide range of scenarios. Many of these scenarios may not be legal for
    HTTP/2 and so may never hit the function, but it's worth validating that it
    behaves as expected anyway.
    """
    @given(HEADERS_STRATEGY)
    def test_range_of_acceptable_outputs(self, headers):
        """
        validate_headers either returns the data unchanged or throws a
        ProtocolError.
        """
        try:
            assert headers == h2.utilities.validate_headers(headers)
        except h2.exceptions.ProtocolError:
            assert True

    def test_invalid_pseudo_headers(self):
        headers = [(b':custom', b'value')]
        with pytest.raises(h2.exceptions.ProtocolError):
            h2.utilities.validate_headers(headers)

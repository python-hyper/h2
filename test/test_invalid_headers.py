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
import h2.settings
import h2.utilities

import hyperframe.frame

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
        base_request_headers + [('host', 'notexample.com')],
        [header for header in base_request_headers
         if header[0] != ':authority'],
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
            last_stream_id=1, error_code=h2.errors.PROTOCOL_ERROR
        )
        assert c.data_to_send() == expected_frame.serialize()

    @pytest.mark.parametrize('headers', invalid_header_blocks)
    def test_headers_event_skipping_validation(self, frame_factory, headers):
        """
        If we have ``validate_inbound_headers`` disabled, then all of these
        invalid header blocks are allowed to pass.
        """
        config = h2.config.H2Configuration(
            client_side=False,
            validate_inbound_headers=False)

        c = h2.connection.H2Connection(config=config)
        c.receive_data(frame_factory.preamble())

        f = frame_factory.build_headers_frame(headers)
        data = f.serialize()

        events = c.receive_data(data)
        assert len(events) == 1
        request_event = events[0]
        assert request_event.headers == headers

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


class TestSendingInvalidFrameSequences(object):
    """
    Trying to send invalid header sequences cause ProtocolErrors to
    be thrown.
    """
    base_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
        ('user-agent', 'someua/0.0.1'),
    ]
    invalid_header_blocks = [
        base_request_headers + [('host', 'notexample.com')],
        [header for header in base_request_headers
         if header[0] != ':authority'],
    ]

    @pytest.mark.parametrize('headers', invalid_header_blocks)
    def test_headers_event(self, frame_factory, headers):
        """
        Test sending invalid headers raise a ProtocolError.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()

        # Clear the data, then try to send headers.
        c.clear_outbound_data_buffer()
        with pytest.raises(h2.exceptions.ProtocolError):
            c.send_headers(1, headers)

    @pytest.mark.parametrize('headers', invalid_header_blocks)
    def test_headers_event_skipping_validation(self, frame_factory, headers):
        """
        If we have ``validate_sent_headers`` disabled, then all of these
        invalid header blocks are allowed to pass.
        """
        config = h2.config.H2Configuration(
            validate_sent_headers=False)

        c = h2.connection.H2Connection(config=config)
        c.initiate_connection()

        # Clear the data, then send headers.
        c.clear_outbound_data_buffer()
        c.send_headers(1, headers)


class TestFilter(object):
    """
    Test the filter function directly.

    These tests exists to confirm the behaviour of the filter function in a
    wide range of scenarios. Many of these scenarios may not be legal for
    HTTP/2 and so may never hit the function, but it's worth validating that it
    behaves as expected anyway.
    """
    validation_functions = [
        h2.utilities.validate_headers,
        h2.utilities.validate_sent_headers
    ]

    hdr_validation_combos = [
        h2.utilities.HeaderValidationFlags(is_client, is_trailer)
        for is_client, is_trailer in [
            (True, True),
            (True, False),
            (False, True),
            (False, False)
        ]
    ]

    @pytest.mark.parametrize('validation_function', validation_functions)
    @pytest.mark.parametrize('hdr_validation_flags', hdr_validation_combos)
    @given(headers=HEADERS_STRATEGY)
    def test_range_of_acceptable_outputs(self,
                                         headers,
                                         validation_function,
                                         hdr_validation_flags):
        """
        The header validation functions either return the data unchanged
        or throw a ProtocolError.
        """
        try:
            assert headers == list(validation_function(
                headers, hdr_validation_flags))
        except h2.exceptions.ProtocolError:
            assert True

    @pytest.mark.parametrize('hdr_validation_flags', hdr_validation_combos)
    def test_invalid_pseudo_headers(self, hdr_validation_flags):
        headers = [(b':custom', b'value')]
        with pytest.raises(h2.exceptions.ProtocolError):
            h2.utilities.validate_headers(headers, hdr_validation_flags)

    @pytest.mark.parametrize('validation_function', validation_functions)
    @pytest.mark.parametrize('hdr_validation_flags', hdr_validation_combos)
    def test_matching_authority_host_headers(self,
                                             validation_function,
                                             hdr_validation_flags):
        """
        If a header block has :authority and Host headers and they match,
        the headers should pass through unchanged.
        """
        headers = [
            (b':authority', b'example.com'),
            (b':path', b'/'),
            (b':scheme', b'https'),
            (b':method', b'GET'),
            (b'host', b'example.com'),
        ]
        assert headers == h2.utilities.validate_headers(
            headers, hdr_validation_flags)


class TestOversizedHeaders(object):
    """
    Tests that oversized header blocks are correctly rejected. This replicates
    the "HPACK Bomb" attack, and confirms that we're resistent against it.
    """
    request_header_block = [
        (b':method', b'GET'),
        (b':authority', b'example.com'),
        (b':scheme', b'https'),
        (b':path', b'/'),
    ]

    response_header_block = [
        (b':status', b'200'),
    ]

    # The first header block contains a single header that fills the header
    # table. To do that, we'll give it a single-character header name and a
    # 4063 byte header value. This will make it exactly the size of the header
    # table. It must come last, so that it evicts all other headers.
    # This block must be appended to either a request or response block.
    first_header_block = [
        (b'a', b'a' * 4063),
    ]

    # The second header "block" is actually a custom HEADERS frame body that
    # simply repeatedly refers to the first entry for 16kB. Each byte has the
    # high bit set (0x80), and then uses the remaining 7 bits to encode the
    # number 62 (0x3e), leading to a repeat of the byte 0xbe.
    second_header_block = b'\xbe' * 2**14

    def test_hpack_bomb_request(self, frame_factory):
        """
        A HPACK bomb request causes the connection to be torn down with the
        error code ENHANCE_YOUR_CALM.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            self.request_header_block + self.first_header_block
        )
        data = f.serialize()
        c.receive_data(data)

        # Build the attack payload.
        attack_frame = hyperframe.frame.HeadersFrame(stream_id=3)
        attack_frame.data = self.second_header_block
        attack_frame.flags.add('END_HEADERS')
        data = attack_frame.serialize()

        with pytest.raises(h2.exceptions.DenialOfServiceError):
            c.receive_data(data)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=1, error_code=h2.errors.ENHANCE_YOUR_CALM
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_hpack_bomb_response(self, frame_factory):
        """
        A HPACK bomb response causes the connection to be torn down with the
        error code ENHANCE_YOUR_CALM.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(
            stream_id=1, headers=self.request_header_block
        )
        c.send_headers(
            stream_id=3, headers=self.request_header_block
        )
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            self.response_header_block + self.first_header_block
        )
        data = f.serialize()
        c.receive_data(data)

        # Build the attack payload.
        attack_frame = hyperframe.frame.HeadersFrame(stream_id=3)
        attack_frame.data = self.second_header_block
        attack_frame.flags.add('END_HEADERS')
        data = attack_frame.serialize()

        with pytest.raises(h2.exceptions.DenialOfServiceError):
            c.receive_data(data)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=0, error_code=h2.errors.ENHANCE_YOUR_CALM
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_hpack_bomb_push(self, frame_factory):
        """
        A HPACK bomb push causes the connection to be torn down with the
        error code ENHANCE_YOUR_CALM.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(
            stream_id=1, headers=self.request_header_block
        )
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            self.response_header_block + self.first_header_block
        )
        data = f.serialize()
        c.receive_data(data)

        # Build the attack payload. We need to shrink it by four bytes because
        # the promised_stream_id consumes four bytes of body.
        attack_frame = hyperframe.frame.PushPromiseFrame(stream_id=3)
        attack_frame.promised_stream_id = 2
        attack_frame.data = self.second_header_block[:-4]
        attack_frame.flags.add('END_HEADERS')
        data = attack_frame.serialize()

        with pytest.raises(h2.exceptions.DenialOfServiceError):
            c.receive_data(data)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=0, error_code=h2.errors.ENHANCE_YOUR_CALM
        )
        assert c.data_to_send() == expected_frame.serialize()

    def test_reject_headers_when_list_size_shrunk(self, frame_factory):
        """
        When we've shrunk the header list size, we reject new header blocks
        that violate the new size.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        # Receive the first request, which causes no problem.
        f = frame_factory.build_headers_frame(
            stream_id=1,
            headers=self.request_header_block
        )
        data = f.serialize()
        c.receive_data(data)

        # Now, send a settings change. It's un-ACKed at this time. A new
        # request arrives, also without incident.
        c.update_settings({h2.settings.MAX_HEADER_LIST_SIZE: 50})
        c.clear_outbound_data_buffer()
        f = frame_factory.build_headers_frame(
            stream_id=3,
            headers=self.request_header_block
        )
        data = f.serialize()
        c.receive_data(data)

        # We get a SETTINGS ACK.
        f = frame_factory.build_settings_frame({}, ack=True)
        data = f.serialize()
        c.receive_data(data)

        # Now a third request comes in. This explodes.
        f = frame_factory.build_headers_frame(
            stream_id=5,
            headers=self.request_header_block
        )
        data = f.serialize()

        with pytest.raises(h2.exceptions.DenialOfServiceError):
            c.receive_data(data)

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=3, error_code=h2.errors.ENHANCE_YOUR_CALM
        )
        assert c.data_to_send() == expected_frame.serialize()

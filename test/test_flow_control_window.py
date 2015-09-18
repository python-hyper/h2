# -*- coding: utf-8 -*-
"""
test_flow_control
~~~~~~~~~~~~~~~~~

Tests of the flow control management in h2
"""
import pytest

import h2.connection
import h2.exceptions


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

        assert c.flow_control_window(1) == self.DEFAULT_FLOW_WINDOW

    def test_flow_control_decreases_with_sent_data(self):
        """
        When data is sent on a stream, the flow control window should drop.
        """
        c = h2.connection.H2Connection()
        c.send_headers(1, self.example_request_headers)
        c.send_data(1, b'some data')

        remaining_length = self.DEFAULT_FLOW_WINDOW - len(b'some data')
        assert (c.flow_control_window(1) == remaining_length)

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
        assert (c.flow_control_window(2) == remaining_length)

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

# -*- coding: utf-8 -*-
"""
test_flow_control
~~~~~~~~~~~~~~~~~

Tests of the flow control management in h2
"""
import pytest
import time

from hypothesis import given
from hypothesis.strategies import integers

import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions
import h2.settings


class TestConcurrentStreamOpenPerformance(object):
    """
    Tests the performance of concurrently opening streams
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]
    server_config = h2.config.H2Configuration(client_side=False)

    DEFAULT_FLOW_WINDOW = 65535

    def test_concurrent_stream_open_performance(self, frame_factory):
        """
        Opening many concurrent streams does not take too long
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        start = time.time()
        for i in xrange(5000):
            c.send_headers(1 + (2 * i), self.example_request_headers, end_stream=False)
            c.clear_outbound_data_buffer()
        end = time.time()

        print end-start
        assert end-start < 3


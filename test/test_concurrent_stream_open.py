# -*- coding: utf-8 -*-
"""
test_flow_control
~~~~~~~~~~~~~~~~~

Tests of the flow control management in h2
"""
import logging
import time


import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions
import h2.settings
from h2.stream import H2Stream, sync_state_change


class TestConcurrentStreamOpen(object):
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
    client_config = h2.config.H2Configuration(client_side=True)

    DEFAULT_FLOW_WINDOW = 65535

    def test_sync_state_change_incr_conditional(self, frame_factory):

        @sync_state_change
        def wrap_send_headers(self, *args, **kwargs):
            return self.send_headers(*args, **kwargs)

        def dummy_callback(*args, **kwargs):
            pass

        c = h2.connection.H2Connection()
        s = H2Stream(1, self.client_config, self.DEFAULT_FLOW_WINDOW,
                     self.DEFAULT_FLOW_WINDOW, dummy_callback,
                     dummy_callback)
        s.max_outbound_frame_size = 65536

        wrap_send_headers(s, self.example_request_headers,
                          c.encoder, end_stream=False)
        assert s.open

    def test_concurrent_stream_open_performance(self, frame_factory):
        """
        Opening many concurrent streams isn't prohibitively expensive
        """
        num_concurrent_streams = 10000

        c = h2.connection.H2Connection()
        c.initiate_connection()
        start = time.time()
        for i in range(num_concurrent_streams):
            c.send_headers(
                1 + (2 * i), self.example_request_headers, end_stream=False)
            c.clear_outbound_data_buffer()
        end = time.time()

        run_time = end - start
        assert run_time < 5

    def test_stream_open_with_debug_logging(self, frame_factory):
        """
        Test that opening a stream with debug logging works
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.config.logger.setLevel(logging.DEBUG)
        c.send_headers(
            1, self.example_request_headers, end_stream=False)
        c.clear_outbound_data_buffer()

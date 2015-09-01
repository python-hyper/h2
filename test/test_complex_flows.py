# -*- coding: utf-8 -*-
"""
test_complex_flows
~~~~~~~~~~~~~~~~~~

Test more complicated flows.

These tests are more difficult to construct, but provide complete examples of
how this class would be used in a production environment. Essentially, each
one drives the state machine with a fake set of sends and receives.

These tests additionally act as examples of how this module is to be used.

The tests in this module make minimal assertions about specific features of the
library: they only assert in the broadest terms. Their primary purpose is to
ensure that the API is respected.
"""
import h2
import hyperframe.frame as frame

from helpers import build_headers_frame, build_data_frames


class TestClientFlows(object):
    """
    Flows that represent the client side of a connection.
    """
    def test_readme(self):
        """
        The flow from README.rst works as demonstrated.
        """
        # Construct input data.
        headers = [
            (':authority', 'example.com'),
            (':path', '/'),
            (':scheme', 'https'),
            (':method', 'POST'),
        ]
        data = b'key=value&key2=value2'

        # Pre-bake the response
        resp_headers = [
            (':status', '200'),
            ('server', 'hyper-h2-testserv'),
            ('content-length', '20'),
            ('content-type', 'text/plain'),
        ]
        resp_data = b'\x01' * 20
        received_header_frames = build_headers_frame(resp_headers)
        received_data_frames = build_data_frames(resp_data)

        # Run the code from the README
        conn = h2.Connection()
        header_frames, stream_id = conn.send_headers(headers)
        data_frames = conn.send_data(stream_id, data)
        response_headers = conn.recv_header_frames(received_header_frames)
        response_data = conn.recv_data_frames(received_data_frames)

        assert len(header_frames) > 0
        assert stream_id == 1
        assert len(data_frames) > 0
        assert response_headers == resp_headers
        assert response_data == resp_data

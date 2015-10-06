# -*- coding: utf-8 -*-
"""
test_complex_logic
~~~~~~~~~~~~~~~~

More complex tests that try to do more.

Certain tests don't really eliminate incorrect behaviour unless they do quite
a bit. These tests should live here, to keep the pain in once place rather than
hide it in the other parts of the test suite.
"""
import h2


class TestComplexClient(object):
    """
    Complex tests for client-side stacks.
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

    def test_correctly_count_server_streams(self, frame_factory):
        """
        We correctly count the number of server streams, both inbound and
        outbound.
        """
        # This test makes no sense unless you do both inbound and outbound,
        # because it's important to confirm that we count them correctly.
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        expected_inbound_streams = expected_outbound_streams = 0

        assert c.open_inbound_streams == expected_inbound_streams
        assert c.open_outbound_streams == expected_outbound_streams

        for stream_id in range(1, 15, 2):
            # Open an outbound stream
            c.send_headers(stream_id, self.example_request_headers)
            expected_outbound_streams += 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            # Receive a pushed stream (to create an inbound one). This doesn't
            # open until we also receive headers.
            f = frame_factory.build_push_promise_frame(
                stream_id=stream_id,
                promised_stream_id=stream_id+1,
                headers=self.example_request_headers,
            )
            c.receive_data(f.serialize())
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            f = frame_factory.build_headers_frame(
                stream_id=stream_id+1,
                headers=self.example_response_headers,
            )
            c.receive_data(f.serialize())
            expected_inbound_streams += 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

        for stream_id in range(13, 0, -2):
            # Close an outbound stream.
            c.end_stream(stream_id)

            # Stream doesn't close until both sides close it.
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            f = frame_factory.build_headers_frame(
                stream_id=stream_id,
                headers=self.example_response_headers,
                flags=['END_STREAM'],
            )
            c.receive_data(f.serialize())
            expected_outbound_streams -= 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            # Pushed streams can only be closed remotely.
            f = frame_factory.build_headers_frame(
                stream_id=stream_id+1,
                headers=self.example_response_headers,
                flags=['END_STREAM'],
            )
            c.receive_data(f.serialize())
            expected_inbound_streams -= 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

        assert c.open_inbound_streams == 0
        assert c.open_outbound_streams == 0


class TestComplexServer(object):
    """
    Complex tests for server-side stacks.
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

    def test_correctly_count_server_streams(self, frame_factory):
        """
        We correctly count the number of server streams, both inbound and
        outbound.
        """
        # This test makes no sense unless you do both inbound and outbound,
        # because it's important to confirm that we count them correctly.
        c = h2.connection.H2Connection(client_side=False)
        c.receive_data(frame_factory.preamble())
        expected_inbound_streams = expected_outbound_streams = 0

        assert c.open_inbound_streams == expected_inbound_streams
        assert c.open_outbound_streams == expected_outbound_streams

        for stream_id in range(1, 15, 2):
            # Receive an inbound stream.
            f = frame_factory.build_headers_frame(
                headers=self.example_request_headers,
                stream_id=stream_id,
            )
            c.receive_data(f.serialize())
            expected_inbound_streams += 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            # Push a stream (to create a outbound one). This doesn't open
            # until we send our response headers.
            c.push_stream(stream_id, stream_id+1, self.example_request_headers)
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            c.send_headers(stream_id+1, self.example_response_headers)
            expected_outbound_streams += 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

        for stream_id in range(13, 0, -2):
            # Close an inbound stream.
            f = frame_factory.build_data_frame(
                data=b'',
                flags=['END_STREAM'],
                stream_id=stream_id,
            )
            c.receive_data(f.serialize())

            # Stream doesn't close until both sides close it.
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            c.send_data(stream_id, b'', end_stream=True)
            expected_inbound_streams -= 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

            # Pushed streams, however, we can close ourselves.
            c.send_data(
                stream_id=stream_id+1,
                data=b'',
                end_stream=True,
            )
            expected_outbound_streams -= 1
            assert c.open_inbound_streams == expected_inbound_streams
            assert c.open_outbound_streams == expected_outbound_streams

        assert c.open_inbound_streams == 0
        assert c.open_outbound_streams == 0

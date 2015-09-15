# -*- coding: utf-8 -*-
"""
test_interacting_stacks
~~~~~~~~~~~~~~~~~~~~~~~

These tests run two entities, a client and a server, in parallel threads. These
two entities talk to each other, running what amounts to a number of carefully
controlled simulations of real flows.

This is to ensure that the stack as a whole behaves intelligently in both
client and server cases.

These tests are long, complex, and somewhat brittle, so they aren't in general
recommended for writing the majority of test cases. Their purposes is primarily
to validate that the top-level API of the library behaves as described.

We should also consider writing helper functions to reduce the complexity of
these tests, so that they can be written more easily, as they are remarkably
useful.
"""
import threaded_tests

import h2.connection
import h2.events


class TestCommunication(threaded_tests.ThreadedTestCase):
    """
    Test that two communicating state machines can work together.
    """
    def test_basic_request_response(self):
        """
        A request issued by hyper-h2 can be responded to by hyper-h2.
        """
        request_headers = {
            ':method': 'GET',
            ':path': '/',
            ':authority': 'example.com',
            ':scheme': 'https',
            'User-Agent': 'test-client/0.1.0',
        }
        response_headers = {
            ':status': '204',
            'Server': 'test-server/0.1.0',
            'Content-Length': '0',
        }

        def client(sock, send_event, recv_event):
            c = h2.connection.H2Connection()

            # Do the handshake. First send the preamble.
            c.initiate_connection()
            sock.sendall(c.data_to_send())
            send_event.set()

            # Then receive the remote preamble.
            recv_event.wait(0.2)
            recv_event.clear()
            events = c.receive_data(sock.recv(65535))
            assert len(events) == 1
            assert isinstance(events[0], h2.events.RemoteSettingsChanged)

            # Send a request.
            events = c.send_headers(1, request_headers, end_stream=True)
            assert not events
            sock.sendall(c.data_to_send())
            send_event.set()

            # Validate the response.
            recv_event.wait(0.2)
            recv_event.clear()
            events = c.receive_data(sock.recv(65535))
            assert len(events) == 2
            assert isinstance(events[0], h2.events.ResponseReceived)
            assert events[0].stream_id == 1
            assert dict(events[0].headers) == response_headers
            assert isinstance(events[1], h2.events.StreamEnded)
            assert events[1].stream_id == 1

            sock.close()

        def server(sock, send_event, recv_event):
            c = h2.connection.H2Connection(client_side=False)

            # First, read for the preamble.
            recv_event.wait(0.2)
            recv_event.clear()
            events = c.receive_data(sock.recv(65535))
            assert len(events) == 1
            assert isinstance(events[0], h2.events.RemoteSettingsChanged)

            # Send our preamble back.
            c.initiate_connection()
            sock.sendall(c.data_to_send())
            send_event.set()

            # Listen for the request.
            recv_event.wait(0.2)
            recv_event.clear()
            events = c.receive_data(sock.recv(65535))
            assert len(events) == 2
            assert isinstance(events[0], h2.events.RequestReceived)
            assert events[0].stream_id == 1
            assert dict(events[0].headers) == request_headers
            assert isinstance(events[1], h2.events.StreamEnded)
            assert events[1].stream_id == 1

            # Send our response.
            events = c.send_headers(1, response_headers, end_stream=True)
            assert not events
            sock.sendall(c.data_to_send())
            send_event.set()

            sock.close()

        self.run_until_complete(client, server)

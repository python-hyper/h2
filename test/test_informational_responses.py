# -*- coding: utf-8 -*-
"""
test_informational_responses
~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests that validate that hyper-h2 correctly handles informational (1XX)
responses in its state machine.
"""
import h2.connection
import h2.events


class TestReceivingInformationalResponses(object):
    """
    Tests for receiving informational responses.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
        ('expect', '100-continue'),
    ]
    example_informational_headers = [
        (':status', '100'),
        ('server', 'fake-serv/0.1.0')
    ]
    example_response_headers = [
        (':status', '200'),
        ('server', 'fake-serv/0.1.0')
    ]
    example_trailers = [
        ('trailer', 'you-bet'),
    ]

    def test_single_informational_response(self, frame_factory):
        """
        When receiving a informational response, the appropriate event is
        signaled.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 1
        event = events[0]

        assert isinstance(event, h2.events.InformationalResponseReceived)
        assert event.headers == self.example_informational_headers
        assert event.stream_id == 1

    def test_receiving_multiple_header_blocks(self, frame_factory):
        """
        At least three header blocks can be received: informational, headers,
        trailers.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f1 = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        f2 = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            stream_id=1,
        )
        f3 = frame_factory.build_headers_frame(
            headers=self.example_trailers,
            stream_id=1,
            flags=['END_STREAM'],
        )
        events = c.receive_data(
            f1.serialize() + f2.serialize() + f3.serialize()
        )

        assert len(events) == 4

        assert isinstance(events[0], h2.events.InformationalResponseReceived)
        assert events[0].headers == self.example_informational_headers
        assert events[0].stream_id == 1

        assert isinstance(events[1], h2.events.ResponseReceived)
        assert events[1].headers == self.example_response_headers
        assert events[1].stream_id == 1

        assert isinstance(events[2], h2.events.TrailersReceived)
        assert events[2].headers == self.example_trailers
        assert events[2].stream_id == 1

    def test_receiving_multiple_informational_responses(self, frame_factory):
        """
        More than one informational response is allowed.
        """
        c = h2.connection.H2Connection(client_side=True)
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        f1 = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        f2 = frame_factory.build_headers_frame(
            headers=[(':status', '101')],
            stream_id=1,
        )
        events = c.receive_data(f1.serialize() + f2.serialize())

        assert len(events) == 2

        assert isinstance(events[0], h2.events.InformationalResponseReceived)
        assert events[0].headers == self.example_informational_headers
        assert events[0].stream_id == 1

        assert isinstance(events[1], h2.events.InformationalResponseReceived)
        assert events[1].headers == [(':status', '101')]
        assert events[1].stream_id == 1


class TestSendingInformationalResponses(object):
    """
    Tests for sending informational responses.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
        ('expect', '100-continue'),
    ]
    example_informational_headers = [
        (':status', '100'),
        ('server', 'fake-serv/0.1.0')
    ]
    example_response_headers = [
        (':status', '200'),
        ('server', 'fake-serv/0.1.0')
    ]
    example_trailers = [
        ('trailer', 'you-bet'),
    ]

    def test_single_informational_response(self, frame_factory):
        """
        When sending a informational response, the appropriate frames are
        emitted.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=1
        )
        c.receive_data(f.serialize())
        c.clear_outbound_data_buffer()
        frame_factory.refresh_encoder()

        c.send_headers(
            stream_id=1,
            headers=self.example_informational_headers,
        )

        f = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        assert c.data_to_send() == f.serialize()

    def test_sending_multiple_header_blocks(self, frame_factory):
        """
        At least three header blocks can be sent: informational, headers,
        trailers.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=1
        )
        c.receive_data(f.serialize())
        c.clear_outbound_data_buffer()
        frame_factory.refresh_encoder()

        # Send the three header blocks.
        c.send_headers(
            stream_id=1,
            headers=self.example_informational_headers
        )
        c.send_headers(
            stream_id=1,
            headers=self.example_response_headers
        )
        c.send_headers(
            stream_id=1,
            headers=self.example_trailers,
            end_stream=True
        )

        # Check that we sent them properly.
        f1 = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        f2 = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            stream_id=1,
        )
        f3 = frame_factory.build_headers_frame(
            headers=self.example_trailers,
            stream_id=1,
            flags=['END_STREAM']
        )
        assert (
            c.data_to_send() ==
            f1.serialize() + f2.serialize() + f3.serialize()
        )

    def test_sending_multiple_informational_responses(self, frame_factory):
        """
        More than one informational response is allowed.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=1
        )
        c.receive_data(f.serialize())
        c.clear_outbound_data_buffer()
        frame_factory.refresh_encoder()

        # Send two informational responses.
        c.send_headers(
            stream_id=1,
            headers=self.example_informational_headers
        )
        c.send_headers(
            stream_id=1,
            headers=[(':status', '101')]
        )

        # Check we sent them both.
        f1 = frame_factory.build_headers_frame(
            headers=self.example_informational_headers,
            stream_id=1,
        )
        f2 = frame_factory.build_headers_frame(
            headers=[(':status', '101')],
            stream_id=1,
        )
        assert c.data_to_send() == f1.serialize() + f2.serialize()

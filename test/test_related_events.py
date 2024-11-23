# -*- coding: utf-8 -*-
"""
test_related_events.py
~~~~~~~~~~~~~~~~~~~~~~

Specific tests to validate the "related events" logic used by certain events
inside hyper-h2.
"""
import pytest

import h2.config
import h2.connection
import h2.events


class TestRelatedEvents(object):
    """
    Related events correlate all those events that happen on a single frame.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]

    example_request_headers_bytes = [
        (b':authority', b'example.com'),
        (b':path', b'/'),
        (b':scheme', b'https'),
        (b':method', b'GET'),
    ]

    example_response_headers = [
        (':status', '200'),
        ('server', 'fake-serv/0.1.0')
    ]

    informational_response_headers = [
        (':status', '100'),
        ('server', 'fake-serv/0.1.0')
    ]

    example_trailers = [
        ('another', 'field'),
    ]

    server_config = h2.config.H2Configuration(client_side=False)

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_request_received_related_all(self, frame_factory, request_headers):
        """
        RequestReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=request_headers,
            flags=['END_STREAM', 'PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 3
        base_event = events[0]
        other_events = events[1:]

        assert base_event.stream_ended in other_events
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)
        assert base_event.priority_updated in other_events
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_request_received_related_priority(self, frame_factory, request_headers):
        """
        RequestReceived can be related to PriorityUpdated.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=request_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        priority_updated_event = events[1]

        assert base_event.priority_updated is priority_updated_event
        assert base_event.stream_ended is None
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_request_received_related_stream_ended(self, frame_factory, request_headers):
        """
        RequestReceived can be related to StreamEnded.
        """
        c = h2.connection.H2Connection(config=self.server_config)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=request_headers,
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        stream_ended_event = events[1]

        assert base_event.stream_ended is stream_ended_event
        assert base_event.priority_updated is None
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_response_received_related_nothing(self, frame_factory, request_headers):
        """
        ResponseReceived is ordinarily related to no events.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 1
        base_event = events[0]

        assert base_event.stream_ended is None
        assert base_event.priority_updated is None

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_response_received_related_all(self, frame_factory, request_headers):
        """
        ResponseReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['END_STREAM', 'PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 3
        base_event = events[0]
        other_events = events[1:]

        assert base_event.stream_ended in other_events
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)
        assert base_event.priority_updated in other_events
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_response_received_related_priority(self, frame_factory, request_headers):
        """
        ResponseReceived can be related to PriorityUpdated.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        priority_updated_event = events[1]

        assert base_event.priority_updated is priority_updated_event
        assert base_event.stream_ended is None
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_response_received_related_stream_ended(self, frame_factory, request_headers):
        """
        ResponseReceived can be related to StreamEnded.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        stream_ended_event = events[1]

        assert base_event.stream_ended is stream_ended_event
        assert base_event.priority_updated is None
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_trailers_received_related_all(self, frame_factory, request_headers):
        """
        TrailersReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
        )
        c.receive_data(f.serialize())

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_trailers,
            flags=['END_STREAM', 'PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 3
        base_event = events[0]
        other_events = events[1:]

        assert base_event.stream_ended in other_events
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)
        assert base_event.priority_updated in other_events
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_trailers_received_related_stream_ended(self, frame_factory, request_headers):
        """
        TrailersReceived can be related to StreamEnded by itself.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
        )
        c.receive_data(f.serialize())

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_trailers,
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        stream_ended_event = events[1]

        assert base_event.stream_ended is stream_ended_event
        assert base_event.priority_updated is None
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_informational_response_related_nothing(self, frame_factory, request_headers):
        """
        InformationalResponseReceived in the standard case is related to
        nothing.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.informational_response_headers,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 1
        base_event = events[0]

        assert base_event.priority_updated is None

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_informational_response_received_related_all(self, frame_factory, request_headers):
        """
        InformationalResponseReceived has one possible related event:
        PriorityUpdated, fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.informational_response_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        priority_updated_event = events[1]

        assert base_event.priority_updated is priority_updated_event
        assert isinstance(
            base_event.priority_updated, h2.events.PriorityUpdated
        )

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_data_received_normally_relates_to_nothing(self, frame_factory, request_headers):
        """
        A plain DATA frame leads to DataReceieved with no related events.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
        )
        c.receive_data(f.serialize())

        input_frame = frame_factory.build_data_frame(
            data=b'some data',
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 1
        base_event = events[0]

        assert base_event.stream_ended is None

    @pytest.mark.parametrize("request_headers", [example_request_headers, example_request_headers_bytes])
    def test_data_received_related_stream_ended(self, frame_factory, request_headers):
        """
        DataReceived can be related to StreamEnded by itself.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=request_headers)

        f = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
        )
        c.receive_data(f.serialize())

        input_frame = frame_factory.build_data_frame(
            data=b'some data',
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        base_event = events[0]
        stream_ended_event = events[1]

        assert base_event.stream_ended is stream_ended_event
        assert isinstance(base_event.stream_ended, h2.events.StreamEnded)

# -*- coding: utf-8 -*-
"""
test_related_events.py
~~~~~~~~~~~~~~~~~~~~~~

Specific tests to validate the "related events" logic used by certain events
inside hyper-h2.
"""
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

    def test_request_received_related_all(self, frame_factory):
        """
        RequestReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            flags=['END_STREAM', 'PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 3
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event,
                (
                    h2.events.RequestReceived,
                    h2.events.PriorityUpdated,
                    h2.events.StreamEnded,
                )
            )
            assert event.related_events == set_events

    def test_request_received_related_priority(self, frame_factory):
        """
        RequestReceived can be related to PriorityUpdated.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.RequestReceived, h2.events.PriorityUpdated)
            )
            assert event.related_events == set_events

    def test_request_received_related_stream_ended(self, frame_factory):
        """
        RequestReceived can be related to StreamEnded.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.RequestReceived, h2.events.StreamEnded)
            )
            assert event.related_events == set_events

    def test_response_received_related_all(self, frame_factory):
        """
        ResponseReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['END_STREAM', 'PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 3
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event,
                (
                    h2.events.ResponseReceived,
                    h2.events.PriorityUpdated,
                    h2.events.StreamEnded,
                )
            )
            assert event.related_events == set_events

    def test_response_received_related_priority(self, frame_factory):
        """
        ResponseReceived can be related to PriorityUpdated.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.ResponseReceived, h2.events.PriorityUpdated)
            )
            assert event.related_events == set_events

    def test_response_received_related_stream_ended(self, frame_factory):
        """
        ResponseReceived can be related to StreamEnded.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.example_response_headers,
            flags=['END_STREAM'],
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.ResponseReceived, h2.events.StreamEnded)
            )
            assert event.related_events == set_events

    def test_trailers_received_related_all(self, frame_factory):
        """
        TrailersReceived has two possible related events: PriorityUpdated and
        StreamEnded, all fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

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
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event,
                (
                    h2.events.TrailersReceived,
                    h2.events.PriorityUpdated,
                    h2.events.StreamEnded,
                )
            )
            assert event.related_events == set_events

    def test_trailers_received_related_stream_ended(self, frame_factory):
        """
        TrailersReceived can be related to StreamEnded by itself.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

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
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.TrailersReceived, h2.events.StreamEnded)
            )
            assert event.related_events == set_events

    def test_informational_response_received_related_all(self, frame_factory):
        """
        InformationalResponseReceived has one possible related event:
        PriorityUpdated, fired when a single HEADERS frame is received.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

        input_frame = frame_factory.build_headers_frame(
            headers=self.informational_response_headers,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=0,
            exclusive=False,
        )
        events = c.receive_data(input_frame.serialize())

        assert len(events) == 2
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event,
                (
                    h2.events.InformationalResponseReceived,
                    h2.events.PriorityUpdated,
                )
            )
            assert event.related_events == set_events

    def test_data_received_related_stream_ended(self, frame_factory):
        """
        DataReceived can be related to StreamEnded by itself.
        """
        c = h2.connection.H2Connection()
        c.initiate_connection()
        c.send_headers(stream_id=1, headers=self.example_request_headers)

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
        set_events = frozenset(events)

        for event in events:
            assert isinstance(
                event, (h2.events.DataReceived, h2.events.StreamEnded)
            )
            assert event.related_events == set_events

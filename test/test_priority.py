# -*- coding: utf-8 -*-
"""
test_priority
~~~~~~~~~~~~~

Test the priority logic of Hyper-h2.
"""
import pytest

import h2.connection
import h2.errors
import h2.events
import h2.exceptions
import h2.stream


class TestPriority(object):
    """
    Basic priority tests.
    """
    example_request_headers = [
        (':authority', 'example.com'),
        (':path', '/'),
        (':scheme', 'https'),
        (':method', 'GET'),
    ]

    def test_receiving_priority_emits_priority_update(self, frame_factory):
        """
        Receiving a priority frame emits a PriorityUpdated event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_priority_frame(
            stream_id=1,
            weight=255,
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 1
        assert not c.data_to_send()

        event = events[0]
        assert isinstance(event, h2.events.PriorityUpdated)
        assert event.stream_id == 1
        assert event.depends_on == 0
        assert event.weight == 256
        assert event.exclusive is False

    def test_headers_with_priority_info(self, frame_factory):
        """
        Receiving a HEADERS frame with priority information on it emits a
        PriorityUpdated event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=3,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=1,
            exclusive=True,
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 2
        assert not c.data_to_send()

        event = events[1]
        assert isinstance(event, h2.events.PriorityUpdated)
        assert event.stream_id == 3
        assert event.depends_on == 1
        assert event.weight == 16
        assert event.exclusive is True

    def test_streams_may_not_depend_on_themselves(self, frame_factory):
        """
        A stream adjusted to depend on itself causes a Protocol Error.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=3,
            flags=['PRIORITY'],
            stream_weight=15,
            depends_on=1,
            exclusive=True,
        )
        c.receive_data(f.serialize())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_priority_frame(
            stream_id=3,
            depends_on=3,
            weight=15
        )
        with pytest.raises(h2.exceptions.ProtocolError):
            c.receive_data(f.serialize())

        expected_frame = frame_factory.build_goaway_frame(
            last_stream_id=3,
            error_code=h2.errors.PROTOCOL_ERROR,
        )
        assert c.data_to_send() == expected_frame.serialize()

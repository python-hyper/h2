# -*- coding: utf-8 -*-
"""
test_priority
~~~~~~~~~~~~~

Test the priority logic of Hyper-h2.
"""
import h2.connection
import h2.events
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
        Receiving a priority frame emits a PriorityUpdate event.
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
        assert isinstance(event, h2.events.PriorityUpdate)
        assert event.stream_id == 1
        assert event.depends_on == 0
        assert event.weight == 255
        assert event.exclusive is False

    def test_headers_with_priority_info(self, frame_factory):
        """
        Receiving a HEADERS frame with priority information on it emits a
        PriorityUpdate event.
        """
        c = h2.connection.H2Connection(client_side=False)
        c.initiate_connection()
        c.receive_data(frame_factory.preamble())
        c.clear_outbound_data_buffer()

        f = frame_factory.build_headers_frame(
            headers=self.example_request_headers,
            stream_id=3,
            flags=['PRIORITY'],
            stream_weight=16,
            depends_on=1,
            exclusive=True,
        )
        events = c.receive_data(f.serialize())

        assert len(events) == 2
        assert not c.data_to_send()

        event = events[1]
        assert isinstance(event, h2.events.PriorityUpdate)
        assert event.stream_id == 3
        assert event.depends_on == 1
        assert event.weight == 16
        assert event.exclusive is True

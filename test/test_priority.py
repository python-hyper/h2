# -*- coding: utf-8 -*-
"""
test_priority
~~~~~~~~~~~~~

Test the priority logic of Hyper-h2. Currently Hyper-h2 has a no-op logic for
priority (which is to say, it's ignored), but in future we'll try to do
something reasonable with it.
"""
import h2.connection
import h2.stream


class TestPriority(object):
    """
    Basic priority tests.
    """
    def test_receiving_priority_does_nothing(self, frame_factory):
        """
        Receiving a priority frame does nothing.
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

        assert not events
        assert not c.data_to_send()

# -*- coding: utf-8 -*-
"""
test_state_machines
~~~~~~~~~~~~~~~~~~~

These tests validate the state machines directly. Writing meaningful tests for
this case can be tricky, so the majority of these tests use Hypothesis to try
to talk about general behaviours rather than specific cases
"""
import h2.connection
import h2.exceptions
import h2.stream

from hypothesis import given
from hypothesis.strategies import sampled_from


class TestConnectionStateMachine(object):
    """
    Tests of the connection state machine.
    """
    @given(state=sampled_from(h2.connection.ConnectionState),
           input_=sampled_from(h2.connection.ConnectionInputs))
    def test_state_transitions(self, state, input_):
        c = h2.connection.H2ConnectionStateMachine()
        c.state = state

        try:
            c.process_input(input_)
        except h2.exceptions.ProtocolError:
            assert c.state == h2.connection.ConnectionState.CLOSED
        else:
            assert c.state in h2.connection.ConnectionState


class TestStreamStateMachine(object):
    """
    Tests of the stream state machine.
    """
    @given(state=sampled_from(h2.stream.StreamState),
           input_=sampled_from(h2.stream.StreamInputs))
    def test_state_transitions(self, state, input_):
        s = h2.stream.H2StreamStateMachine(stream_id=1)
        s.state = state

        try:
            s.process_input(input_)
        except h2.exceptions.ProtocolError:
            assert s.state == h2.stream.StreamState.CLOSED
        else:
            assert s.state in h2.stream.StreamState

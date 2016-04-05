# -*- coding: utf-8 -*-
"""
h2/stream
~~~~~~~~~

An implementation of a HTTP/2 stream.
"""
import warnings

from enum import Enum, IntEnum
from hyperframe.frame import (
    HeadersFrame, ContinuationFrame, DataFrame, WindowUpdateFrame,
    RstStreamFrame, PushPromiseFrame,
)

from .errors import STREAM_CLOSED
from .events import (
    RequestReceived, ResponseReceived, DataReceived, WindowUpdated,
    StreamEnded, PushedStreamReceived, StreamReset, TrailersReceived,
    InformationalResponseReceived,
)
from .exceptions import (
    ProtocolError, StreamClosedError, InvalidBodyLengthError
)
from .utilities import guard_increment_window, is_informational_response


class StreamState(IntEnum):
    IDLE = 0
    RESERVED_REMOTE = 1
    RESERVED_LOCAL = 2
    OPEN = 3
    HALF_CLOSED_REMOTE = 4
    HALF_CLOSED_LOCAL = 5
    CLOSED = 6


class StreamInputs(Enum):
    SEND_HEADERS = 0
    SEND_PUSH_PROMISE = 1
    SEND_RST_STREAM = 2
    SEND_DATA = 3
    SEND_WINDOW_UPDATE = 4
    SEND_END_STREAM = 5
    RECV_HEADERS = 6
    RECV_PUSH_PROMISE = 7
    RECV_RST_STREAM = 8
    RECV_DATA = 9
    RECV_WINDOW_UPDATE = 10
    RECV_END_STREAM = 11
    RECV_CONTINUATION = 12  # Added in 2.0.0
    SEND_INFORMATIONAL_HEADERS = 13  # Added in 2.2.0
    RECV_INFORMATIONAL_HEADERS = 14  # Added in 2.2.0


# This array is initialized once, and is indexed by the stream states above.
# It indicates whether a stream in the given state is open. The reason we do
# this is that we potentially check whether a stream in a given state is open
# quite frequently: given that we check so often, we should do so in the
# fastest and most performant way possible.
STREAM_OPEN = [False for _ in range(0, len(StreamState))]
STREAM_OPEN[StreamState.OPEN] = True
STREAM_OPEN[StreamState.HALF_CLOSED_LOCAL] = True
STREAM_OPEN[StreamState.HALF_CLOSED_REMOTE] = True


class H2StreamStateMachine(object):
    """
    A single HTTP/2 stream state machine.

    This stream object implements basically the state machine described in
    RFC 7540 section 5.1.

    :param stream_id: The stream ID of this stream. This is stored primarily
        for logging purposes.
    """
    def __init__(self, stream_id):
        self.state = StreamState.IDLE
        self.stream_id = stream_id

        #: Whether this peer is the client side of this stream.
        self.client = None

        # Whether trailers have been sent/received on this stream or not.
        self.headers_sent = None
        self.trailers_sent = None
        self.headers_received = None
        self.trailers_received = None

    def process_input(self, input_):
        """
        Process a specific input in the state machine.
        """
        if not isinstance(input_, StreamInputs):
            raise ValueError("Input must be an instance of StreamInputs")

        try:
            func, target_state = _transitions[(self.state, input_)]
        except KeyError:
            old_state = self.state
            self.state = StreamState.CLOSED
            raise ProtocolError(
                "Invalid input %s in state %s" % (input_, old_state)
            )
        else:
            previous_state = self.state
            self.state = target_state
            if func is not None:
                try:
                    return func(self, previous_state)
                except ProtocolError:
                    self.state = StreamState.CLOSED
                    raise
                except AssertionError as e:  # pragma: no cover
                    self.state = StreamState.CLOSED
                    raise ProtocolError(e)

            return []

    def request_sent(self, previous_state):
        """
        Fires when a request is sent.
        """
        self.client = True
        self.headers_sent = True
        return []

    def response_sent(self, previous_state):
        """
        Fires when something that should be a response is sent. This 'response'
        may actually be trailers.
        """
        if not self.headers_sent:
            if self.client is True or self.client is None:
                raise ProtocolError("Client cannot send responses.")
            self.headers_sent = True
        else:
            assert not self.trailers_sent
            self.trailers_sent = True

        return []

    def request_received(self, previous_state):
        """
        Fires when a request is received.
        """
        assert not self.headers_received
        assert not self.trailers_received

        self.client = False
        self.headers_received = True
        event = RequestReceived()

        event.stream_id = self.stream_id
        return [event]

    def response_received(self, previous_state):
        """
        Fires when a response is received. Also disambiguates between responses
        and trailers.
        """
        if not self.headers_received:
            assert self.client is True
            self.headers_received = True
            event = ResponseReceived()
        else:
            assert not self.trailers_received
            self.trailers_received = True
            event = TrailersReceived()

        event.stream_id = self.stream_id
        return [event]

    def data_received(self, previous_state):
        """
        Fires when data is received.
        """
        event = DataReceived()
        event.stream_id = self.stream_id
        return [event]

    def window_updated(self, previous_state):
        """
        Fires when a window update frame is received.
        """
        event = WindowUpdated()
        event.stream_id = self.stream_id
        return [event]

    def stream_ended(self, previous_state):
        """
        Fires when a stream is cleanly ended.
        """
        event = StreamEnded()
        event.stream_id = self.stream_id
        return [event]

    def stream_reset(self, previous_state):
        """
        Fired when a stream is forcefully reset.
        """
        event = StreamReset()
        event.stream_id = self.stream_id
        return [event]

    def send_new_pushed_stream(self, previous_state):
        """
        Fires on the newly pushed stream, when pushed by the local peer.

        No event here, but definitionally this peer must be a server.
        """
        assert self.client is None
        self.client = False
        return []

    def recv_new_pushed_stream(self, previous_state):
        """
        Fires on the newly pushed stream, when pushed by the remote peer.

        No event here, but definitionally this peer must be a client.
        """
        assert self.client is None
        self.client = True
        return []

    def send_push_promise(self, previous_state):
        """
        Fires on the already-existing stream when a PUSH_PROMISE frame is sent.
        We may only send PUSH_PROMISE frames if we're a server.
        """
        if self.client is True:
            raise ProtocolError("Cannot push streams from client peers.")

        return []

    def recv_push_promise(self, previous_state):
        """
        Fires on the already-existing stream when a PUSH_PROMISE frame is
        received. We may only receive PUSH_PROMISE frames if we're a client.

        Fires a PushedStreamReceived event.
        """
        if not self.client:
            if self.client is None:  # pragma: no cover
                msg = "Idle streams cannot receive pushes"
            else:  # pragma: no cover
                msg = "Cannot receive pushed streams as a server"
            raise ProtocolError(msg)

        event = PushedStreamReceived()
        event.parent_stream_id = self.stream_id
        return [event]

    def send_reset(self, previous_state):
        """
        Called when we need to forcefully emit another RST_STREAM frame on
        behalf of the state machine.

        If this is the first time we've done this, we should also hang an event
        off the StreamClosedError so that the user can be informed. We know
        it's the first time we've done this if the stream is currently in a
        state other than CLOSED.
        """
        events = []

        if previous_state != StreamState.CLOSED:
            event = StreamReset()
            event.stream_id = self.stream_id
            event.error_code = STREAM_CLOSED
            event.remote_reset = False
            events.append(event)

        error = StreamClosedError(self.stream_id)
        error._events = events
        raise error

    def send_on_closed_stream(self, previous_state):
        """
        Called when an attempt is made to send data on an already-closed
        stream.

        This essentially overrides the standard logic by throwing a
        more-specific error: StreamClosedError. This is a ProtocolError, so it
        matches the standard API of the state machine, but provides more detail
        to the user.
        """
        assert previous_state == StreamState.CLOSED
        raise StreamClosedError(self.stream_id)

    def push_on_closed_stream(self, previous_state):
        """
        Called when an attempt is made to push on an already-closed stream.

        This essentially overrides the standard logic by providing a more
        useful error message. It's necessary because simply indicating that the
        stream is closed is not enough: there is now a new stream that is not
        allowed to be there. The only recourse is to tear the whole connection
        down.
        """
        assert previous_state == StreamState.CLOSED
        raise ProtocolError("Attempted to push on closed stream.")

    def send_informational_response(self, previous_state):
        """
        Called when an informational header block is sent (that is, a block
        where the :status header has a 1XX value).

        Only enforces that these are sent *before* final headers are sent.
        """
        if self.headers_sent:
            raise ProtocolError("Information response after final response")

        return []

    def recv_informational_response(self, previous_state):
        """
        Called when an informational header block is received (that is, a block
        where the :status header has a 1XX value).
        """
        if self.headers_received:
            raise ProtocolError("Informational response after final response")

        event = InformationalResponseReceived()
        event.stream_id = self.stream_id
        return [event]


# STATE MACHINE
#
# The stream state machine is defined here to avoid the need to allocate it
# repeatedly for each stream. It cannot be defined in the stream class because
# it needs to be able to reference the callbacks defined on the class, but
# because Python's scoping rules are weird the class object is not actually in
# scope during the body of the class object.
#
# For the sake of clarity, we reproduce the RFC 7540 state machine here:
#
#                          +--------+
#                  send PP |        | recv PP
#                 ,--------|  idle  |--------.
#                /         |        |         \
#               v          +--------+          v
#        +----------+          |           +----------+
#        |          |          | send H /  |          |
# ,------| reserved |          | recv H    | reserved |------.
# |      | (local)  |          |           | (remote) |      |
# |      +----------+          v           +----------+      |
# |          |             +--------+             |          |
# |          |     recv ES |        | send ES     |          |
# |   send H |     ,-------|  open  |-------.     | recv H   |
# |          |    /        |        |        \    |          |
# |          v   v         +--------+         v   v          |
# |      +----------+          |           +----------+      |
# |      |   half   |          |           |   half   |      |
# |      |  closed  |          | send R /  |  closed  |      |
# |      | (remote) |          | recv R    | (local)  |      |
# |      +----------+          |           +----------+      |
# |           |                |                 |           |
# |           | send ES /      |       recv ES / |           |
# |           | send R /       v        send R / |           |
# |           | recv R     +--------+   recv R   |           |
# | send R /  `----------->|        |<-----------'  send R / |
# | recv R                 | closed |               recv R   |
# `----------------------->|        |<----------------------'
#                          +--------+
#
#    send:   endpoint sends this frame
#    recv:   endpoint receives this frame
#
#    H:  HEADERS frame (with implied CONTINUATIONs)
#    PP: PUSH_PROMISE frame (with implied CONTINUATIONs)
#    ES: END_STREAM flag
#    R:  RST_STREAM frame
#
# For the purposes of this state machine we treat HEADERS and their
# associated CONTINUATION frames as a single jumbo frame. The protocol
# allows/requires this by preventing other frames from being interleved in
# between HEADERS/CONTINUATION frames. However, if a CONTINUATION frame is
# received without a prior HEADERS frame, it *will* be passed to this state
# machine. The state machine should always reject that frame, either as an
# invalid transition or because the stream is closed.
#
# There is a confusing relationship around PUSH_PROMISE frames. The state
# machine above considers them to be frames belonging to the new stream,
# which is *somewhat* true. However, they are sent with the stream ID of
# their related stream, and are only sendable in some cases.
# For this reason, our state machine implementation below allows for
# PUSH_PROMISE frames both in the IDLE state (as in the diagram), but also
# in the OPEN, HALF_CLOSED_LOCAL, and HALF_CLOSED_REMOTE states.
# Essentially, for hyper-h2, PUSH_PROMISE frames are effectively sent on
# two streams.
#
# The _transitions dictionary contains a mapping of tuples of
# (state, input) to tuples of (side_effect_function, end_state). This
# map contains all allowed transitions: anything not in this map is
# invalid and immediately causes a transition to ``closed``.
_transitions = {
    # State: idle
    (StreamState.IDLE, StreamInputs.SEND_HEADERS):
        (H2StreamStateMachine.request_sent, StreamState.OPEN),
    (StreamState.IDLE, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.request_received, StreamState.OPEN),
    (StreamState.IDLE, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.IDLE, StreamInputs.SEND_PUSH_PROMISE):
        (H2StreamStateMachine.send_new_pushed_stream,
            StreamState.RESERVED_LOCAL),
    (StreamState.IDLE, StreamInputs.RECV_PUSH_PROMISE):
        (H2StreamStateMachine.recv_new_pushed_stream,
            StreamState.RESERVED_REMOTE),

    # State: reserved local
    (StreamState.RESERVED_LOCAL, StreamInputs.SEND_HEADERS):
        (None, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.RESERVED_LOCAL, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.RESERVED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE):
        (None, StreamState.RESERVED_LOCAL),
    (StreamState.RESERVED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.RESERVED_LOCAL),
    (StreamState.RESERVED_LOCAL, StreamInputs.SEND_RST_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.RESERVED_LOCAL, StreamInputs.RECV_RST_STREAM):
        (H2StreamStateMachine.stream_reset, StreamState.CLOSED),

    # State: reserved remote
    (StreamState.RESERVED_REMOTE, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.response_received,
            StreamState.HALF_CLOSED_LOCAL),
    (StreamState.RESERVED_REMOTE, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.RESERVED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE):
        (None, StreamState.RESERVED_REMOTE),
    (StreamState.RESERVED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.RESERVED_REMOTE),
    (StreamState.RESERVED_REMOTE, StreamInputs.SEND_RST_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.RESERVED_REMOTE, StreamInputs.RECV_RST_STREAM):
        (H2StreamStateMachine.stream_reset, StreamState.CLOSED),

    # State: open
    (StreamState.OPEN, StreamInputs.SEND_HEADERS):
        (H2StreamStateMachine.response_sent, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.response_received, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.SEND_DATA):
        (None, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.data_received, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.SEND_END_STREAM):
        (None, StreamState.HALF_CLOSED_LOCAL),
    (StreamState.OPEN, StreamInputs.RECV_END_STREAM):
        (H2StreamStateMachine.stream_ended, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.OPEN, StreamInputs.SEND_WINDOW_UPDATE):
        (None, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.SEND_RST_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.OPEN, StreamInputs.RECV_RST_STREAM):
        (H2StreamStateMachine.stream_reset, StreamState.CLOSED),
    (StreamState.OPEN, StreamInputs.SEND_PUSH_PROMISE):
        (H2StreamStateMachine.send_push_promise, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.RECV_PUSH_PROMISE):
        (H2StreamStateMachine.recv_push_promise, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.SEND_INFORMATIONAL_HEADERS):
        (H2StreamStateMachine.send_informational_response, StreamState.OPEN),
    (StreamState.OPEN, StreamInputs.RECV_INFORMATIONAL_HEADERS):
        (H2StreamStateMachine.recv_informational_response, StreamState.OPEN),

    # State: half-closed remote
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_HEADERS):
        (H2StreamStateMachine.response_sent, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_DATA):
        (None, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_END_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE):
        (None, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.HALF_CLOSED_REMOTE),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_RST_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_RST_STREAM):
        (H2StreamStateMachine.stream_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_PUSH_PROMISE):
        (H2StreamStateMachine.send_push_promise,
            StreamState.HALF_CLOSED_REMOTE),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_PUSH_PROMISE):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_CONTINUATION):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_INFORMATIONAL_HEADERS):
        (H2StreamStateMachine.send_informational_response,
            StreamState.HALF_CLOSED_REMOTE),

    # State: half-closed local
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.response_received,
            StreamState.HALF_CLOSED_LOCAL),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.data_received, StreamState.HALF_CLOSED_LOCAL),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_END_STREAM):
        (H2StreamStateMachine.stream_ended, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE):
        (None, StreamState.HALF_CLOSED_LOCAL),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.HALF_CLOSED_LOCAL),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_RST_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_RST_STREAM):
        (H2StreamStateMachine.stream_reset, StreamState.CLOSED),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_PUSH_PROMISE):
        (H2StreamStateMachine.recv_push_promise,
            StreamState.HALF_CLOSED_LOCAL),
    (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_INFORMATIONAL_HEADERS):
        (H2StreamStateMachine.recv_informational_response,
            StreamState.HALF_CLOSED_LOCAL),

    # State: closed
    (StreamState.CLOSED, StreamInputs.RECV_WINDOW_UPDATE):
        (H2StreamStateMachine.window_updated, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.RECV_RST_STREAM):
        (None, StreamState.CLOSED),  # Swallow further RST_STREAMs

    # While closed, all other received frames should cause RST_STREAM
    # frames to be emitted. END_STREAM is always carried *by* a frame,
    # so it should do nothing.
    (StreamState.CLOSED, StreamInputs.RECV_HEADERS):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.RECV_DATA):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.RECV_PUSH_PROMISE):
        (H2StreamStateMachine.push_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.RECV_END_STREAM):
        (None, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.RECV_CONTINUATION):
        (H2StreamStateMachine.send_reset, StreamState.CLOSED),

    # Also, users should be forbidden from sending on closed streams.
    (StreamState.CLOSED, StreamInputs.SEND_HEADERS):
        (H2StreamStateMachine.send_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.SEND_PUSH_PROMISE):
        (H2StreamStateMachine.push_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.SEND_RST_STREAM):
        (H2StreamStateMachine.send_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.SEND_DATA):
        (H2StreamStateMachine.send_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.SEND_WINDOW_UPDATE):
        (H2StreamStateMachine.send_on_closed_stream, StreamState.CLOSED),
    (StreamState.CLOSED, StreamInputs.SEND_END_STREAM):
        (H2StreamStateMachine.send_on_closed_stream, StreamState.CLOSED),
}


class H2Stream(object):
    """
    A low-level HTTP/2 stream object. This handles building and receiving
    frames and maintains per-stream state.

    This wraps a HTTP/2 Stream state machine implementation, ensuring that
    frames can only be sent/received when the stream is in a valid state.
    Attempts to create frames that cannot be sent will raise a
    ``ProtocolError``.
    """
    def __init__(self, stream_id):
        self.state_machine = H2StreamStateMachine(stream_id)
        self.stream_id = stream_id
        self.max_outbound_frame_size = None

        # The curent value of the stream flow control windows
        self.outbound_flow_control_window = 65535
        self.inbound_flow_control_window = 65535

        # The expected content length, if any.
        self._expected_content_length = None

        # The actual received content length. Always tracked.
        self._actual_content_length = 0

    @property
    def open(self):
        """
        Whether the stream is 'open' in any sense: that is, whether it counts
        against the number of concurrent streams.
        """
        # RFC 7540 Section 5.1.2 defines 'open' for this purpose to mean either
        # the OPEN state or either of the HALF_CLOSED states. Perplexingly,
        # this excludes the reserved states.
        # For more detail on why we're doing this in this slightly weird way,
        # see the comment on ``STREAM_OPEN`` at the top of the file.
        return STREAM_OPEN[self.state_machine.state]

    @property
    def closed(self):
        """
        Whether the stream is closed.
        """
        return self.state_machine.state == StreamState.CLOSED

    def send_headers(self, headers, encoder, end_stream=False):
        """
        Returns a list of HEADERS/CONTINUATION frames to emit as either headers
        or trailers.
        """
        # Convert headers to two-tuples.
        # FIXME: The fallback for dictionary headers is to be removed in 3.0.
        try:
            warnings.warn(
                "Implicit conversion of dictionaries to two-tuples for "
                "headers is deprecated and will be removed in 3.0.",
                DeprecationWarning
            )
            headers = headers.items()
        except AttributeError:
            headers = headers

        # Because encoding headers makes an irreversible change to the header
        # compression context, we make the state transition before we encode
        # them.

        # First, check if we're a client. If we are, no problem: if we aren't,
        # we need to scan the header block to see if this is an informational
        # response.
        input_ = StreamInputs.SEND_HEADERS
        if ((not self.state_machine.client) and
                is_informational_response(headers)):
            if end_stream:
                raise ProtocolError(
                    "Cannot set END_STREAM on informational responses."
                )

            input_ = StreamInputs.SEND_INFORMATIONAL_HEADERS

        # This does not trigger any events.
        events = self.state_machine.process_input(input_)
        assert not events

        hf = HeadersFrame(self.stream_id)
        frames = self._build_headers_frames(headers, encoder, hf)

        if end_stream:
            # Not a bug: the END_STREAM flag is valid on the initial HEADERS
            # frame, not the CONTINUATION frames that follow.
            self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
            frames[0].flags.add('END_STREAM')

        if self.state_machine.trailers_sent and not end_stream:
            raise ProtocolError("Trailers must have END_STREAM set.")

        return frames

    def push_stream_in_band(self, related_stream_id, headers, encoder):
        """
        Returns a list of PUSH_PROMISE/CONTINUATION frames to emit as a pushed
        stream header. Called on the stream that has the PUSH_PROMISE frame
        sent on it.
        """
        # Because encoding headers makes an irreversible change to the header
        # compression context, we make the state transition *first*.

        # This does not trigger any events.
        events = self.state_machine.process_input(
            StreamInputs.SEND_PUSH_PROMISE
        )
        assert not events

        ppf = PushPromiseFrame(self.stream_id)
        ppf.promised_stream_id = related_stream_id
        frames = self._build_headers_frames(headers, encoder, ppf)

        return frames

    def locally_pushed(self):
        """
        Mark this stream as one that was pushed by this peer. Must be called
        immediately after initialization. Sends no frames, simply updates the
        state machine.
        """
        # This does not trigger any events.
        events = self.state_machine.process_input(
            StreamInputs.SEND_PUSH_PROMISE
        )
        assert not events
        return []

    def send_data(self, data, end_stream=False):
        """
        Prepare some data frames. Optionally end the stream.

        .. warning:: Does not perform flow control checks.
        """
        self.state_machine.process_input(StreamInputs.SEND_DATA)

        df = DataFrame(self.stream_id)
        df.data = data
        if end_stream:
            self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
            df.flags.add('END_STREAM')

        self.outbound_flow_control_window -= len(data)
        assert self.outbound_flow_control_window >= 0

        return [df]

    def end_stream(self):
        """
        End a stream without sending data.
        """
        self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
        df = DataFrame(self.stream_id)
        df.flags.add('END_STREAM')
        return [df]

    def increase_flow_control_window(self, increment):
        """
        Increase the size of the flow control window for the remote side.
        """
        self.state_machine.process_input(StreamInputs.SEND_WINDOW_UPDATE)
        wuf = WindowUpdateFrame(self.stream_id)
        wuf.window_increment = increment
        return [wuf]

    def receive_push_promise_in_band(self, promised_stream_id, headers):
        """
        Receives a push promise frame sent on this stream, pushing a remote
        stream. This is called on the stream that has the PUSH_PROMISE sent
        on it.
        """
        events = self.state_machine.process_input(
            StreamInputs.RECV_PUSH_PROMISE
        )
        events[0].pushed_stream_id = promised_stream_id
        events[0].headers = headers
        return [], events

    def remotely_pushed(self):
        """
        Mark this stream as one that was pushed by the remote peer. Must be
        called immediately after initialization. Sends no frames, simply
        updates the state machine.
        """
        events = self.state_machine.process_input(
            StreamInputs.RECV_PUSH_PROMISE
        )
        return [], events

    def receive_headers(self, headers, end_stream):
        """
        Receive a set of headers (or trailers).
        """
        if is_informational_response(headers):
            if end_stream:
                raise ProtocolError(
                    "Cannot set END_STREAM on informational responses"
                )
            input_ = StreamInputs.RECV_INFORMATIONAL_HEADERS
        else:
            input_ = StreamInputs.RECV_HEADERS

        events = self.state_machine.process_input(input_)

        if end_stream:
            events += self.state_machine.process_input(
                StreamInputs.RECV_END_STREAM
            )

        self._initialize_content_length(headers)

        if isinstance(events[0], TrailersReceived):
            if not end_stream:
                raise ProtocolError("Trailers must have END_STREAM set")

        events[0].headers = headers
        return [], events

    def receive_data(self, data, end_stream, flow_control_len):
        """
        Receive some data.
        """
        events = self.state_machine.process_input(StreamInputs.RECV_DATA)
        self.inbound_flow_control_window -= flow_control_len
        self._track_content_length(len(data), end_stream)

        if end_stream:
            events += self.state_machine.process_input(
                StreamInputs.RECV_END_STREAM
            )

        events[0].data = data
        events[0].flow_controlled_length = flow_control_len
        return [], events

    def receive_window_update(self, increment):
        """
        Handle a WINDOW_UPDATE increment.
        """
        events = self.state_machine.process_input(
            StreamInputs.RECV_WINDOW_UPDATE
        )
        events[0].delta = increment
        self.outbound_flow_control_window = guard_increment_window(
            self.outbound_flow_control_window,
            increment
        )

        return [], events

    def receive_continuation(self):
        """
        A naked CONTINUATION frame has been received. This is always an error,
        but the type of error it is depends on the state of the stream and must
        transition the state of the stream, so we need to handle it.
        """
        self.state_machine.process_input(
            StreamInputs.RECV_CONTINUATION
        )
        assert False, "Should not be reachable"

    def reset_stream(self, error_code=0):
        """
        Close the stream locally. Reset the stream with an error code.
        """
        self.state_machine.process_input(StreamInputs.SEND_RST_STREAM)

        rsf = RstStreamFrame(self.stream_id)
        rsf.error_code = error_code
        return [rsf]

    def stream_reset(self, frame):
        """
        Handle a stream being reset remotely.
        """
        events = self.state_machine.process_input(StreamInputs.RECV_RST_STREAM)

        if events:
            # We don't fire an event if this stream is already closed.
            events[0].error_code = frame.error_code

        return [], events

    def _build_headers_frames(self,
                              headers,
                              encoder,
                              first_frame):
        """
        Helper method to build headers or push promise frames.
        """
        headers = ((name.lower(), value) for name, value in headers)
        encoded_headers = encoder.encode(headers)

        # Slice into blocks of max_outbound_frame_size. Be careful with this:
        # it only works right because we never send padded frames or priority
        # information on the frames. Revisit this if we do.
        header_blocks = [
            encoded_headers[i:i+self.max_outbound_frame_size]
            for i in range(
                0, len(encoded_headers), self.max_outbound_frame_size
            )
        ]

        frames = []
        first_frame.data = header_blocks[0]
        frames.append(first_frame)

        for block in header_blocks[1:]:
            cf = ContinuationFrame(self.stream_id)
            cf.data = block
            frames.append(cf)

        frames[-1].flags.add('END_HEADERS')
        return frames

    def _initialize_content_length(self, headers):
        """
        Checks the headers for a content-length header and initializes the
        _expected_content_length field from it. It's not an error for no
        Content-Length header to be present.
        """
        for n, v in headers:
            if n == 'content-length':
                try:
                    self._expected_content_length = int(v, 10)
                except ValueError:
                    raise ProtocolError(
                        "Invalid content-length header: %s" % v
                    )

                return

    def _track_content_length(self, length, end_stream):
        """
        Update the expected content length in response to data being received.
        Validates that the appropriate amount of data is sent. Always updates
        the received data, but only validates the length against the
        content-length header if one was sent.

        :param length: The length of the body chunk received.
        :param end_stream: If this is the last body chunk received.
        """
        self._actual_content_length += length
        actual = self._actual_content_length
        expected = self._expected_content_length

        if expected is not None:
            if expected < actual:
                raise InvalidBodyLengthError(expected, actual)

            if end_stream and expected != actual:
                raise InvalidBodyLengthError(expected, actual)

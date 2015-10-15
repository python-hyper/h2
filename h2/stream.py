# -*- coding: utf-8 -*-
"""
h2/stream
~~~~~~~~~

An implementation of a HTTP/2 stream.
"""
from enum import Enum
from hyperframe.frame import (
    HeadersFrame, ContinuationFrame, DataFrame, WindowUpdateFrame,
    RstStreamFrame, PushPromiseFrame,
)

from .events import (
    RequestReceived, ResponseReceived, DataReceived, WindowUpdated,
    StreamEnded, PushedStreamReceived, StreamReset, TrailersReceived
)
from .exceptions import ProtocolError


class StreamState(Enum):
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
    SEND_PRIORITY = 6
    RECV_HEADERS = 7
    RECV_PUSH_PROMISE = 8
    RECV_RST_STREAM = 9
    RECV_DATA = 10
    RECV_WINDOW_UPDATE = 11
    RECV_END_STREAM = 12
    RECV_PRIORITY = 13


class H2StreamStateMachine(object):
    """
    A single HTTP/2 stream state machine.

    This stream object implements basically the state machine described in
    RFC 7540 section 5.1.

    :param stream_id: The stream ID of this stream. This is stored primarily
        for logging purposes.
    """
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
    # between HEADERS/CONTINUATION frames.
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

        # The _transitions dictionary contains a mapping of tuples of
        # (state, input) to tuples of (side_effect_function, end_state). This
        # map contains all allowed transitions: anything not in this map is
        # invalid and immediately causes a transition to ``closed``.
        self._transitions = {
            # State: idle
            (StreamState.IDLE, StreamInputs.SEND_HEADERS):
                (self.request_sent, StreamState.OPEN),
            (StreamState.IDLE, StreamInputs.RECV_HEADERS):
                (self.request_received, StreamState.OPEN),
            (StreamState.IDLE, StreamInputs.SEND_PUSH_PROMISE):
                (self.send_new_pushed_stream, StreamState.RESERVED_LOCAL),
            (StreamState.IDLE, StreamInputs.RECV_PUSH_PROMISE):
                (self.recv_new_pushed_stream, StreamState.RESERVED_REMOTE),
            (StreamState.IDLE, StreamInputs.SEND_PRIORITY):
                (None, StreamState.IDLE),
            (StreamState.IDLE, StreamInputs.RECV_PRIORITY):
                (None, StreamState.IDLE),

            # State: reserved local
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_HEADERS):
                (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE):
                (None, StreamState.RESERVED_LOCAL),
            (StreamState.RESERVED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.RESERVED_LOCAL),
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_RST_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.RESERVED_LOCAL, StreamInputs.RECV_RST_STREAM):
                (self.stream_reset, StreamState.CLOSED),
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_PRIORITY):
                (None, StreamState.RESERVED_LOCAL),
            (StreamState.RESERVED_LOCAL, StreamInputs.RECV_PRIORITY):
                (None, StreamState.RESERVED_LOCAL),

            # State: reserved remote
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_HEADERS):
                (self.response_received, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.RESERVED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE):
                (None, StreamState.RESERVED_REMOTE),
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.RESERVED_REMOTE),
            (StreamState.RESERVED_REMOTE, StreamInputs.SEND_RST_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_RST_STREAM):
                (self.stream_reset, StreamState.CLOSED),
            (StreamState.RESERVED_REMOTE, StreamInputs.SEND_PRIORITY):
                (None, StreamState.RESERVED_REMOTE),
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_PRIORITY):
                (None, StreamState.RESERVED_REMOTE),

            # State: open
            (StreamState.OPEN, StreamInputs.SEND_HEADERS):
                (self.response_sent, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_HEADERS):
                (self.response_received, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_DATA):
                (None, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_DATA):
                (self.data_received, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_END_STREAM):
                (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.OPEN, StreamInputs.RECV_END_STREAM):
                (self.stream_ended, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.OPEN, StreamInputs.SEND_WINDOW_UPDATE):
                (None, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_RST_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.OPEN, StreamInputs.RECV_RST_STREAM):
                (self.stream_reset, StreamState.CLOSED),
            (StreamState.OPEN, StreamInputs.SEND_PUSH_PROMISE):
                (self.send_push_promise, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_PUSH_PROMISE):
                (self.recv_push_promise, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_PRIORITY):
                (None, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_PRIORITY):
                (None, StreamState.OPEN),

            # State: half-closed remote
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_HEADERS):
                (self.response_sent, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_DATA):
                (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_END_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE):
                (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_RST_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_RST_STREAM):
                (self.stream_reset, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_PUSH_PROMISE):
                (self.send_push_promise, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_PRIORITY):
                (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_PRIORITY):
                (None, StreamState.HALF_CLOSED_REMOTE),

            # State: half-closed local
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_HEADERS):
                (self.response_received, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_DATA):
                (self.data_received, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_END_STREAM):
                (self.stream_ended, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE):
                (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_RST_STREAM):
                (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_RST_STREAM):
                (self.stream_reset, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_PUSH_PROMISE):
                (self.recv_push_promise, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_PRIORITY):
                (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_PRIORITY):
                (None, StreamState.HALF_CLOSED_LOCAL),

            # State: closed
            (StreamState.CLOSED, StreamInputs.RECV_WINDOW_UPDATE):
                (self.window_updated, StreamState.CLOSED),
            (StreamState.CLOSED, StreamInputs.SEND_PRIORITY):
                (None, StreamState.CLOSED),
            (StreamState.CLOSED, StreamInputs.RECV_PRIORITY):
                (None, StreamState.CLOSED),
        }

    def process_input(self, input_):
        """
        Process a specific input in the state machine.
        """
        if not isinstance(input_, StreamInputs):
            raise ValueError("Input must be an instance of StreamInputs")

        try:
            func, target_state = self._transitions[(self.state, input_)]
        except KeyError:
            old_state = self.state
            self.state = StreamState.CLOSED
            raise ProtocolError(
                "Invalid input %s in state %s", input_, old_state
            )
        else:
            self.state = target_state
            if func is not None:
                try:
                    return func()
                except ProtocolError:
                    self.state = StreamState.CLOSED
                    raise
                except AssertionError as e:  # pragma: no cover
                    self.state = StreamState.CLOSED
                    raise ProtocolError(e)

            return []

    def request_sent(self):
        """
        Fires when a request is sent.
        """
        self.client = True
        self.headers_sent = True
        return []

    def response_sent(self):
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

    def request_received(self):
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

    def response_received(self):
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

    def data_received(self):
        """
        Fires when data is received.
        """
        event = DataReceived()
        event.stream_id = self.stream_id
        return [event]

    def window_updated(self):
        """
        Fires when a window update frame is received.
        """
        event = WindowUpdated()
        event.stream_id = self.stream_id
        return [event]

    def stream_ended(self):
        """
        Fires when a stream is cleanly ended.
        """
        event = StreamEnded()
        event.stream_id = self.stream_id
        return [event]

    def stream_reset(self):
        """
        Fired when a stream is forcefully reset.
        """
        event = StreamReset()
        event.stream_id = self.stream_id
        return [event]

    def send_new_pushed_stream(self):
        """
        Fires on the newly pushed stream, when pushed by the local peer.

        No event here, but definitionally this peer must be a server.
        """
        assert self.client is None
        self.client = False
        return []

    def recv_new_pushed_stream(self):
        """
        Fires on the newly pushed stream, when pushed by the remote peer.

        No event here, but definitionally this peer must be a client.
        """
        assert self.client is None
        self.client = True
        return []

    def send_push_promise(self):
        """
        Fires on the already-existing stream when a PUSH_PROMISE frame is sent.
        We may only send PUSH_PROMISE frames if we're a server.
        """
        if self.client is True:
            raise ProtocolError("Cannot push streams from client peers.")

        return []

    def recv_push_promise(self):
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

    @property
    def open(self):
        """
        Whether the stream is 'open' in any sense: that is, whether it counts
        against the number of concurrent streams.
        """
        # RFC 7540 Section 5.1.2 defines 'open' for this purpose to mean either
        # the OPEN state or either of the HALF_CLOSED states. Perplexingly,
        # this excludes the reserved states.
        return self.state_machine.state in (
            StreamState.OPEN,
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.HALF_CLOSED_REMOTE,
        )

    def send_headers(self, headers, encoder, end_stream=False):
        """
        Returns a list of HEADERS/CONTINUATION frames to emit as either headers
        or trailers.
        """
        # Because encoding headers makes an irreversible change to the header
        # compression context, we make the state transition *first*.
        events = self.state_machine.process_input(StreamInputs.SEND_HEADERS)
        hf = HeadersFrame(self.stream_id)
        frames = self._build_headers_frames(headers, encoder, hf)

        if end_stream:
            # Not a bug: the END_STREAM flag is valid on the initial HEADERS
            # frame, not the CONTINUATION frames that follow.
            self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
            frames[0].flags.add('END_STREAM')

        if self.state_machine.trailers_sent and not end_stream:
            raise ProtocolError("Trailers must have END_STREAM set.")

        return frames, events

    def push_stream_in_band(self, related_stream_id, headers, encoder):
        """
        Returns a list of PUSH_PROMISE/CONTINUATION frames to emit as a pushed
        stream header. Called on the stream that has the PUSH_PROMISE frame
        sent on it.
        """
        # Because encoding headers makes an irreversible change to the header
        # compression context, we make the state transition *first*.
        events = self.state_machine.process_input(
            StreamInputs.SEND_PUSH_PROMISE
        )
        ppf = PushPromiseFrame(self.stream_id)
        ppf.promised_stream_id = related_stream_id
        frames = self._build_headers_frames(headers, encoder, ppf)

        return frames, events

    def locally_pushed(self):
        """
        Mark this stream as one that was pushed by this peer. Must be called
        immediately after initialization. Sends no frames, simply updates the
        state machine.
        """
        events = self.state_machine.process_input(
            StreamInputs.SEND_PUSH_PROMISE
        )
        return [], events

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

        return [df], []

    def end_stream(self):
        """
        End a stream without sending data.
        """
        self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
        df = DataFrame(self.stream_id)
        df.flags.add('END_STREAM')
        return [df], []

    def increase_flow_control_window(self, increment):
        """
        Increase the size of the flow control window for the remote side.
        """
        self.state_machine.process_input(StreamInputs.SEND_WINDOW_UPDATE)
        wuf = WindowUpdateFrame(self.stream_id)
        wuf.window_increment = increment
        return [wuf], []

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
        events = self.state_machine.process_input(StreamInputs.RECV_HEADERS)

        if end_stream:
            events += self.state_machine.process_input(
                StreamInputs.RECV_END_STREAM
            )

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

        if end_stream:
            events += self.state_machine.process_input(
                StreamInputs.RECV_END_STREAM
            )

        events[0].data = data
        return [], events

    def receive_window_update(self, increment):
        """
        Handle a WINDOW_UPDATE increment.
        """
        events = self.state_machine.process_input(
            StreamInputs.RECV_WINDOW_UPDATE
        )
        events[0].delta = increment
        self.outbound_flow_control_window += increment
        return [], events

    def reset_stream(self, error_code=0):
        """
        Close the stream locally. Reset the stream with an error code.
        """
        self.state_machine.process_input(StreamInputs.SEND_RST_STREAM)

        rsf = RstStreamFrame(self.stream_id)
        rsf.error_code = error_code
        return [rsf], []

    def stream_reset(self, frame):
        """
        Handle a stream being reset remotely.
        """
        events = self.state_machine.process_input(StreamInputs.RECV_RST_STREAM)
        events[0].error_code = frame.error_code
        return [], events

    def priority_changed_remote(self, frame):
        """
        The remote side of the stream sent priority information.
        """
        # TODO: Write a proper priority implementation.
        return []

    def _build_headers_frames(self,
                              headers,
                              encoder,
                              first_frame):
        """
        Helper method to build headers or push promise frames.
        """
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

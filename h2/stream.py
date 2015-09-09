# -*- coding: utf-8 -*-
"""
h2/stream
~~~~~~~~~

An implementation of a HTTP/2 stream.
"""
from enum import Enum
from hyperframe.frame import (
    HeadersFrame, ContinuationFrame, DataFrame, WindowUpdateFrame,
    RstStreamFrame
)

from .events import (
    RequestReceived, ResponseReceived, DataReceived, WindowUpdated
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
    RECV_HEADERS = 6
    RECV_PUSH_PROMISE = 7
    RECV_RST_STREAM = 8
    RECV_DATA = 9
    RECV_WINDOW_UPDATE = 10
    RECV_END_STREAM = 11


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

    def __init__(self, stream_id):
        self.state = StreamState.IDLE
        self.stream_id = stream_id

        #: Whether this peer is the client side of this stream.
        self.client = None

        # The _transitions dictionary contains a mapping of tuples of
        # (state, input) to tuples of (side_effect_function, end_state). This
        # map contains all allowed transitions: anything not in this map is
        # invalid and immediately causes a transition to ``closed``.
        self._transitions = {
            # State: idle
            (StreamState.IDLE, StreamInputs.SEND_HEADERS): (self.request_sent, StreamState.OPEN),
            (StreamState.IDLE, StreamInputs.RECV_HEADERS): (self.request_received, StreamState.OPEN),
            (StreamState.IDLE, StreamInputs.SEND_PUSH_PROMISE): (None, StreamState.RESERVED_LOCAL),
            (StreamState.IDLE, StreamInputs.RECV_PUSH_PROMISE): (None, StreamState.RESERVED_REMOTE),

            # State: reserved local
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_HEADERS): (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE): (None, StreamState.RESERVED_LOCAL),
            (StreamState.RESERVED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.RESERVED_LOCAL),
            (StreamState.RESERVED_LOCAL, StreamInputs.SEND_RST_STREAM): (None, StreamState.CLOSED),
            (StreamState.RESERVED_LOCAL, StreamInputs.RECV_RST_STREAM): (None, StreamState.CLOSED),

            # State: reserved remote
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_HEADERS): (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.RESERVED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE): (None, StreamState.RESERVED_REMOTE),
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.RESERVED_REMOTE),
            (StreamState.RESERVED_REMOTE, StreamInputs.SEND_RST_STREAM): (None, StreamState.CLOSED),
            (StreamState.RESERVED_REMOTE, StreamInputs.RECV_RST_STREAM): (None, StreamState.CLOSED),

            # State: open
            (StreamState.OPEN, StreamInputs.SEND_HEADERS): (self.response_sent, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_HEADERS): (self.response_received, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_DATA): (None, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_DATA): (self.data_received, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_END_STREAM): (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.OPEN, StreamInputs.RECV_END_STREAM): (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.OPEN, StreamInputs.SEND_WINDOW_UPDATE): (None, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.OPEN),
            (StreamState.OPEN, StreamInputs.SEND_RST_STREAM): (None, StreamState.CLOSED),
            (StreamState.OPEN, StreamInputs.RECV_RST_STREAM): (None, StreamState.CLOSED),

            # State: half-closed remote
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_HEADERS): (self.response_sent, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_DATA): (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_END_STREAM): (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_WINDOW_UPDATE): (None, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.HALF_CLOSED_REMOTE),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.SEND_RST_STREAM): (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_REMOTE, StreamInputs.RECV_RST_STREAM): (None, StreamState.CLOSED),

            # State: half-closed local
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_HEADERS): (self.response_received, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_DATA): (self.data_received, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_END_STREAM): (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_WINDOW_UPDATE): (None, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.SEND_RST_STREAM): (None, StreamState.CLOSED),
            (StreamState.HALF_CLOSED_LOCAL, StreamInputs.RECV_RST_STREAM): (None, StreamState.CLOSED),

            # State: closed
            (StreamState.CLOSED, StreamInputs.RECV_WINDOW_UPDATE): (self.window_updated, StreamState.CLOSED),
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

            return []

    def request_sent(self):
        """
        Fires when a request is sent.
        """
        self.client = True
        return []

    def response_sent(self):
        """
        Fires when something that should be a response is sent.
        """
        if self.client is True:
            raise ProtocolError("Client cannot send responses.")

        return []

    def request_received(self):
        """
        Fires when a request is received.
        """
        self.client = False

        event = RequestReceived()
        event.stream_id = self.stream_id
        return [event]

    def response_received(self):
        """
        Fires when a response is received.
        """
        if self.client is not True:
            raise ProtocolError("Non-clients cannot receive responses.")

        event = ResponseReceived()
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
        self.max_inbound_frame_size = None

    def send_headers(self, headers, encoder, end_stream=False):
        """
        Returns a list of HEADERS/CONTINUATION frames to emit as either headers
        or trailers.
        """
        # Because encoding headers makes an irreversible change to the header
        # compression context, we make the state transition *first*.
        events = self.state_machine.process_input(StreamInputs.SEND_HEADERS)
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
        hf = HeadersFrame(self.stream_id)
        hf.data = header_blocks[0]
        frames.append(hf)

        for block in header_blocks[1:]:
            cf = ContinuationFrame(self.stream_id)
            cf.data = block
            frames.append(cf)

        frames[-1].flags.add('END_HEADERS')

        if end_stream:
            # Not a bug: the END_STREAM flag is valid on the initial HEADERS
            # frame, not the CONTINUATION frames that follow.
            self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
            frames[0].flags.add('END_STREAM')

        return frames, events

    def send_data(self, data, end_stream=False):
        """
        Prepare some data frames. Optionally end the stream.
        """
        # TODO: Something something flow control.
        frames = []
        for offset in range(0, len(data), self.max_outbound_frame_size):
            self.state_machine.process_input(StreamInputs.SEND_DATA)
            df = DataFrame(self.stream_id)
            df.data = data[offset:offset+self.max_outbound_frame_size]
            frames.append(df)

        if end_stream:
            self.state_machine.process_input(StreamInputs.SEND_END_STREAM)
            frames[-1].flags.add('END_STREAM')

        return frames, []

    def end_stream(self):
        """
        End a stream without sending data.
        """
        self.state_machine.process_input(StreamInputs.END_STREAM)
        df = DataFrame(self.stream_id)
        df.flags.add('END_STREAM')
        return df, []

    def reset_stream(self):
        """
        Forcefully reset a stream.
        """
        self.state_machine.process_input(StreamInputs.SEND_RST_STREAM)
        rsf = RstStreamFrame(self.stream_id)
        return rsf, []

    def increase_flow_control_window(self, increment):
        """
        Increase the size of the flow control window for the remote side.
        """
        self.state_machine.process_input(StreamInputs.SEND_WINDOW_UPDATE)
        wuf = WindowUpdateFrame(self.stream_id)
        wuf.window_increment = increment
        return wuf, []

    def receive_headers(self, headers, end_stream):
        """
        Receive a set of headers (or trailers).
        """
        events = self.state_machine.process_input(StreamInputs.RECV_HEADERS)

        if end_stream:
            events += self.state_machine.process_input(
                StreamInputs.RECV_END_STREAM
            )

        events[0].headers = headers
        return [], events

    def receive_data(self, data, end_stream):
        """
        Receive some data.
        """
        events = self.state_machine.process_input(StreamInputs.RECV_DATA)

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
        return [], events

    def close(self, error_code=0):
        """
        Close the stream locally. Reset the stream with an error code.
        """
        self.state_machine.process_input(StreamInputs.SEND_RST_STREAM)

        rsf = RstStreamFrame(self.stream_id)
        rsf.error_code = error_code
        return rsf, []

    def stream_reset(self):
        """
        Handle a stream being reset remotely.
        """
        events = self.state_machine.process_input(StreamInputs.RECV_RST_STREAM)
        return [], events

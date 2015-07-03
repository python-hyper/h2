# -*- coding: utf-8 -*-
"""
h2/connection
~~~~~~~~~~~~~

An implementation of a HTTP/2 connection.
"""
from enum import Enum

from hyperframe.frame import (
    GoAwayFrame, WindowUpdateFrame, HeadersFrame, ContinuationFrame, DataFrame,
    RstStreamFrame, PingFrame
)
from hpack.hpack import Encoder

from .exceptions import ProtocolError
from .stream import H2Stream


class ConnectionState(Enum):
    IDLE = 0
    CLIENT_OPEN = 1
    SERVER_OPEN = 2
    CLOSED = 3


class ConnectionInputs(Enum):
    SEND_HEADERS = 0
    SEND_PUSH_PROMISE = 1
    SEND_DATA = 2
    SEND_GOAWAY = 3
    SEND_WINDOW_UPDATE = 4
    SEND_PING = 5
    RECV_HEADERS = 6
    RECV_PUSH_PROMISE = 7
    RECV_DATA = 8
    RECV_GOAWAY = 9
    RECV_WINDOW_UPDATE = 10
    RECV_PING = 11


class H2ConnectionStateMachine(object):
    """
    A single HTTP/2 connection state machine.
    """
    # For the purposes of this state machine we treat HEADERS and their
    # associated CONTINUATION frames as a single jumbo frame. The protocol
    # allows/requires this by preventing other frames from being interleved in
    # between HEADERS/CONTINUATION frames.
    #
    # The _transitions dictionary contains a mapping of tuples of
    # (state, input) to tuples of (side_effect_function, end_state). This map
    # contains all allowed transitions: anything not in this map is invalid
    # and immediately causes a transition to ``closed``.

    SEND_HEADERS = 0
    SEND_PUSH_PROMISE = 1
    SEND_DATA = 2
    SEND_GOAWAY = 3
    SEND_WINDOW_UPDATE = 4
    SEND_PING = 5
    RECV_HEADERS = 6
    RECV_PUSH_PROMISE = 7
    RECV_DATA = 8
    RECV_GOAWAY = 9
    RECV_WINDOW_UPDATE = 10
    RECV_PING = 11

    _transitions = {
        # State: idle
        (ConnectionState.IDLE, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.IDLE, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.SERVER_OPEN),

        # State: open, client side.
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_DATA): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_PING): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PUSH_PROMISE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_DATA): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PING): (None, ConnectionState.CLIENT_OPEN),

        # State: open, server side.
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PUSH_PROMISE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_DATA): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PING): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_DATA): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_PING): (None, ConnectionState.SERVER_OPEN),
    }

    def __init__(self):
        self.state = ConnectionState.IDLE
        self._frame_dispatch_table = {
            HeadersFrame: self._receive_headers_frame,
        }

    def process_input(self, input_):
        """
        Process a specific input in the state machine.
        """
        if not isinstance(input_, ConnectionInputs):
            raise ValueError("Input must be an instance of ConnectionInputs")

        try:
            func, target_state = self._transitions[(self.state, input_)]
        except KeyError:
            self.state = ConnectionState.CLOSED
            raise ProtocolError(
                "Invalid input %s in state %s", input_, self.state
            )
        else:
            self.state = target_state
            if func is not None:
                return func()


class H2Connection(object):
    """
    A low-level HTTP/2 stream object. This handles building and receiving
    frames and maintains per-stream state.

    This wraps a HTTP/2 Stream state machine implementation, ensuring that
    frames can only be sent/received when the stream is in a valid state.
    Attempts to create frames that cannot be sent will raise a
    ``ProtocolError``.
    """
    # The initial maximum outbound frame size. This can be changed by receiving
    # a settings frame.
    DEFAULT_MAX_OUTBOUND_FRAME_SIZE = 65535

    # The initial maximum inbound frame size. This is somewhat arbitrarily
    # chosen.
    DEFAULT_MAX_INBOUND_FRAME_SIZE = 2**24

    def __init__(self, client_side=True):
        self.state_machine = H2ConnectionStateMachine()
        self.streams = {}
        self.highest_stream_id = None
        self.max_outbound_frame_size = self.DEFAULT_MAX_OUTBOUND_FRAME_SIZE
        self.max_inbound_frame_size = self.DEFAULT_MAX_INBOUND_FRAME_SIZE
        self.encoder = Encoder()

        # A private variable to store a sequence of received header frames
        # until completion.
        self._header_frames = []

    def begin_new_stream(self, stream_id):
        """
        Initiate a new stream. By default does nothing.
        """
        if stream_id <= self.highest_stream_id:
            raise ValueError(
                "Stream ID must be larger than %s", self.highest_stream_id
            )

        s = H2Stream(stream_id)
        s.max_inbound_frame_size = self.max_inbound_frame_size
        s.max_outbound_frame_size = self.max_outbound_frame_size
        self.streams[stream_id] = s
        self.highest_stream_id = stream_id
        return s

    def send_headers_on_stream(self, stream_id, headers, end_stream=False):
        """
        Send headers on a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_HEADERS)
        return self.streams[stream_id].send_headers(
            headers, self.encoder, end_stream
        )

    def send_data_on_stream(self, stream_id, data, end_stream=False):
        """
        Send data on a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        return self.streams[stream_id].send_data(data, end_stream)

    def end_stream(self, stream_id):
        """
        End a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        return self.streams[stream_id].end_stream()

    def increment_flow_control_window(self, increment, stream_id=None):
        """
        Increment a flow control window, optionally for a single stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_WINDOW_UPDATE)

        if stream_id is not None:
            return self.streams[stream_id].increase_flow_control_window(
                increment
            )
        else:
            f = WindowUpdateFrame(0)
            f.window_increment = increment
            return f

    def push_stream(self, stream_id, related_stream_id, request_headers):
        """
        Send a push promise.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_PUSH_PROMISE)
        return self.streams[stream_id].push_stream(
            request_headers, related_stream_id
        )

    def ping(self):
        """
        Send a PING frame.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_PING)
        return PingFrame(0)

    def close_connection(self, error_code=None):
        """
        Close a connection. If an error code is provided, a GOAWAY frame will
        be emitted. Otherwise, no frame will be emitted.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_GOAWAY)

        if error_code is not None:
            f = GoAwayFrame(0)
            f.error_code = error_code
            f.last_stream_id = self.highest_stream_id
            return f

    def receive_frame(self, frame):
        """
        Handle a frame received on the connection.
        """
        # I don't love using __class__ here, maybe reconsider it.
        return self._frame_dispatch_table[frame.__class__]

    def _receive_headers_frame(self, frame):
        self.state_machine.process_input(ConnectionInputs.RECV_HEADERS)

        try:
            stream = self.streams[frame.stream_id]
        except KeyError:
            stream = self.begin_new_stream(frame.stream_id)

        return stream.receive_headers('END_STREAM' in frame.flags)

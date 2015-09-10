# -*- coding: utf-8 -*-
"""
h2/connection
~~~~~~~~~~~~~

An implementation of a HTTP/2 connection.
"""
from enum import Enum

from hyperframe.frame import (
    GoAwayFrame, WindowUpdateFrame, HeadersFrame, ContinuationFrame, DataFrame,
    RstStreamFrame, PingFrame, PushPromiseFrame, SettingsFrame
)
from hpack.hpack import Encoder, Decoder

from .events import WindowUpdated, RemoteSettingsChanged
from .exceptions import ProtocolError
from .frame_buffer import FrameBuffer
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
    SEND_SETTINGS = 6
    RECV_HEADERS = 7
    RECV_PUSH_PROMISE = 8
    RECV_DATA = 9
    RECV_GOAWAY = 10
    RECV_WINDOW_UPDATE = 11
    RECV_PING = 12
    RECV_SETTINGS = 13


class H2ConnectionStateMachine(object):
    """
    A single HTTP/2 connection state machine.

    This state machine, while defined in its own class, is logically part of
    the H2Connection class also defined in this file. The state machine itself
    maintains very little state directly, instead focusing entirely on managing
    state transitions.
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

    _transitions = {
        # State: idle
        (ConnectionState.IDLE, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.IDLE, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.IDLE, ConnectionInputs.SEND_SETTINGS): (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_SETTINGS): (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.SEND_WINDOW_UPDATE): (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_WINDOW_UPDATE): (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.SEND_PING): (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_PING): (None, ConnectionState.IDLE),

        # State: open, client side.
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_DATA): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_PING): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_SETTINGS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PUSH_PROMISE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_DATA): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PING): (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_SETTINGS): (None, ConnectionState.CLIENT_OPEN),

        # State: open, server side.
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_HEADERS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PUSH_PROMISE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_DATA): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PING): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_SETTINGS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_HEADERS): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_DATA): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_GOAWAY): (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_PING): (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_SETTINGS): (None, ConnectionState.SERVER_OPEN),
    }

    def __init__(self):
        self.state = ConnectionState.IDLE

    def process_input(self, input_):
        """
        Process a specific input in the state machine.
        """
        if not isinstance(input_, ConnectionInputs):
            raise ValueError("Input must be an instance of ConnectionInputs")

        try:
            func, target_state = self._transitions[(self.state, input_)]
        except KeyError:
            old_state = self.state
            self.state = ConnectionState.CLOSED
            raise ProtocolError(
                "Invalid input %s in state %s", input_, old_state
            )
        else:
            self.state = target_state
            if func is not None:
                return func()

            return []


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
        self.highest_stream_id = 0
        self.max_outbound_frame_size = self.DEFAULT_MAX_OUTBOUND_FRAME_SIZE
        self.max_inbound_frame_size = self.DEFAULT_MAX_INBOUND_FRAME_SIZE
        self.encoder = Encoder()
        self.decoder = Decoder()
        self.client_side = client_side

        # This might want to be an extensible class that does sensible stuff
        # with defaults. For now, a dict will do.
        self.local_settings = {}
        self.remote_settings = {}

        # Buffer for incoming data.
        self.incoming_buffer = FrameBuffer(server=not client_side)

        # A private variable to store a sequence of received header frames
        # until completion.
        self._header_frames = []

        # Data that needs to be sent.
        self.data_to_send = b''

        # When in doubt use dict-dispatch.
        self._frame_dispatch_table = {
            HeadersFrame: self._receive_headers_frame,
            PushPromiseFrame: self._receive_push_promise_frame,
            SettingsFrame: self._receive_settings_frame,
            DataFrame: self._receive_data_frame,
            WindowUpdateFrame: self._receive_window_update_frame,
            PingFrame: self._receive_ping_frame,
        }

    def _prepare_for_sending(self, frames):
        if not frames:
            return
        self.data_to_send += b''.join(f.serialize() for f in frames)

    def begin_new_stream(self, stream_id):
        """
        Initiate a new stream.
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

    def initiate_connection(self):
        """
        Provides any data that needs to be sent at the start of the connection.
        Must be called for both clients and servers.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_SETTINGS)
        if self.client_side:
            preamble = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
        else:
            preamble = b''

        f = SettingsFrame(0)
        for setting, value in self.local_settings.items():
            f.settings[setting] = value

        self.data_to_send += preamble + f.serialize()
        return []

    def get_stream_by_id(self, stream_id):
        """
        Gets a stream by its stream ID. Will create one if one does not already
        exist.
        """
        try:
            return self.streams[stream_id]
        except KeyError:
            return self.begin_new_stream(stream_id)

    def send_headers(self, stream_id, headers, end_stream=False):
        """
        Send headers on a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_HEADERS)
        stream = self.get_stream_by_id(stream_id)
        frames, events = stream.send_headers(
            headers, self.encoder, end_stream
        )
        self._prepare_for_sending(frames)
        return events

    def send_data(self, stream_id, data, end_stream=False):
        """
        Send data on a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        frames, events = self.streams[stream_id].send_data(data, end_stream)
        self._prepare_for_sending(frames)
        return events

    def end_stream(self, stream_id):
        """
        End a given stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        frames, events = self.streams[stream_id].end_stream()
        self._prepare_for_sending(frames)
        return events

    def increment_flow_control_window(self, increment, stream_id=None):
        """
        Increment a flow control window, optionally for a single stream.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_WINDOW_UPDATE)

        if stream_id is not None:
            frames = self.streams[stream_id].increase_flow_control_window(
                increment
            )
        else:
            f = WindowUpdateFrame(0)
            f.window_increment = increment
            frames = [f]

        self._prepare_for_sending(frames)

    def push_stream(self, stream_id, related_stream_id, request_headers):
        """
        Send a push promise.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_PUSH_PROMISE)
        frames = self.streams[stream_id].push_stream(
            request_headers, related_stream_id
        )
        self._prepare_for_sending(frames)

    def ping(self):
        """
        Send a PING frame.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_PING)
        self._prepare_for_sending([PingFrame(0)])

    def reset_stream(self, stream_id):
        """
        Reset a stream frame.
        """
        frames, events = self.streams[stream_id].reset_stream()
        self._prepare_for_sending(frames)
        return events

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
            self._prepare_for_sending([f])

    def receive_data(self, data):
        """
        Pass some received HTTP/2 data to the connection for handling.
        """
        events = []
        self.incoming_buffer.add_data(data)

        for frame in self.incoming_buffer:
            events.extend(self.receive_frame(frame))

        return events

    def receive_frame(self, frame):
        """
        Handle a frame received on the connection.
        """
        # I don't love using __class__ here, maybe reconsider it.
        frames, events = self._frame_dispatch_table[frame.__class__](frame)
        self._prepare_for_sending(frames)
        return events

    def _receive_headers_frame(self, frame):
        """
        Receive a headers frame on the connection.
        """
        # Let's decode the headers.
        headers = self.decoder.decode(frame.data)
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_HEADERS
        )
        stream = self.get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_headers(
            headers,
            'END_STREAM' in frame.flags
        )
        return frames, events + stream_events

    def _receive_push_promise_frame(self, frame):
        """
        Receive a push-promise frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_PUSH_PROMISE
        )
        stream = self.get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_push_promise()
        return frames, events + stream_events

    def _receive_data_frame(self, frame):
        """
        Receive a data frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_DATA
        )
        stream = self.get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_data(
            frame.data,
            'END_STREAM' in frame.flags
        )
        return frames, events + stream_events

    def _receive_settings_frame(self, frame):
        """
        Receive a SETTINGS frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_SETTINGS
        )

        # This is an ack of the local settings. Right now, do nothing.
        if 'ACK' in frame.flags:
            return [], events

        events.append(RemoteSettingsChanged.from_settings(
            self.remote_settings, frame.settings
        ))
        return [], events

    def _receive_window_update_frame(self, frame):
        """
        Receive a WINDOW_UPDATE frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_WINDOW_UPDATE
        )

        if frame.stream_id:
            stream = self.get_stream_by_id(frame.stream_id)
            frames, stream_events = stream.receive_window_update(
                frame.window_increment
            )
        else:
            # FIXME: Should we split this into one event per active stream?
            window_updated_event = WindowUpdated()
            window_updated_event.stream_id = 0
            window_updated_event.delta = frame.window_increment
            stream_events = [window_updated_event]
            frames = []

        return frames, events + stream_events

    def _receive_ping_frame(self, frame):
        """
        Receive a PING frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_PING
        )
        f = PingFrame(0)
        f.flags = set(['ACK'])
        return [f], events

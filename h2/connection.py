# -*- coding: utf-8 -*-
"""
h2/connection
~~~~~~~~~~~~~

An implementation of a HTTP/2 connection.
"""
from enum import Enum

from hyperframe.frame import (
    GoAwayFrame, WindowUpdateFrame, HeadersFrame, DataFrame, PingFrame,
    PushPromiseFrame, SettingsFrame, RstStreamFrame, PriorityFrame,
)
from hpack.hpack import Encoder, Decoder

from .events import (
    WindowUpdated, RemoteSettingsChanged, PingAcknowledged,
    SettingsAcknowledged,
)
from .exceptions import (
    ProtocolError, NoSuchStreamError, FlowControlError, FrameTooLargeError,
    TooManyStreamsError,
)
from .frame_buffer import FrameBuffer
from .settings import Settings
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
    SEND_RST_STREAM = 7
    SEND_PRIORITY = 8
    RECV_HEADERS = 9
    RECV_PUSH_PROMISE = 10
    RECV_DATA = 11
    RECV_GOAWAY = 12
    RECV_WINDOW_UPDATE = 13
    RECV_PING = 14
    RECV_SETTINGS = 15
    RECV_RST_STREAM = 16
    RECV_PRIORITY = 17


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
        (ConnectionState.IDLE, ConnectionInputs.SEND_HEADERS):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.IDLE, ConnectionInputs.RECV_HEADERS):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.IDLE, ConnectionInputs.SEND_SETTINGS):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_SETTINGS):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.SEND_WINDOW_UPDATE):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_WINDOW_UPDATE):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.SEND_PING):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_PING):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.SEND_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.IDLE, ConnectionInputs.SEND_PRIORITY):
            (None, ConnectionState.IDLE),
        (ConnectionState.IDLE, ConnectionInputs.RECV_PRIORITY):
            (None, ConnectionState.IDLE),

        # State: open, client side.
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_HEADERS):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_DATA):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_PING):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_SETTINGS):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_PRIORITY):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_HEADERS):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PUSH_PROMISE):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_DATA):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PING):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_SETTINGS):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.SEND_RST_STREAM):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_RST_STREAM):
            (None, ConnectionState.CLIENT_OPEN),
        (ConnectionState.CLIENT_OPEN, ConnectionInputs.RECV_PRIORITY):
            (None, ConnectionState.CLIENT_OPEN),

        # State: open, server side.
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_HEADERS):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PUSH_PROMISE):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_DATA):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_WINDOW_UPDATE):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PING):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_SETTINGS):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_PRIORITY):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_HEADERS):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_DATA):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_WINDOW_UPDATE):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_PING):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_SETTINGS):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_PRIORITY):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.SEND_RST_STREAM):
            (None, ConnectionState.SERVER_OPEN),
        (ConnectionState.SERVER_OPEN, ConnectionInputs.RECV_RST_STREAM):
            (None, ConnectionState.SERVER_OPEN),
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
            if func is not None:  # pragma: no cover
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
        self.encoder = Encoder()
        self.decoder = Decoder()
        self.client_side = client_side

        # Objects that store settings, including defaults.
        self.local_settings = Settings(client=client_side)
        self.remote_settings = Settings(client=not client_side)

        # The curent value of the connection flow control windows on the
        # connection.
        self.outbound_flow_control_window = (
            self.remote_settings.initial_window_size
        )
        self.inbound_flow_control_window = (
            self.local_settings.initial_window_size
        )

        # Maximum frame sizes in each direction.
        self.max_outbound_frame_size = self.remote_settings.max_frame_size
        self.max_inbound_frame_size = self.local_settings.max_frame_size

        # Buffer for incoming data.
        self.incoming_buffer = FrameBuffer(server=not client_side)

        # A private variable to store a sequence of received header frames
        # until completion.
        self._header_frames = []

        # Data that needs to be sent.
        self._data_to_send = b''

        # When in doubt use dict-dispatch.
        self._frame_dispatch_table = {
            HeadersFrame: self._receive_headers_frame,
            PushPromiseFrame: self._receive_push_promise_frame,
            SettingsFrame: self._receive_settings_frame,
            DataFrame: self._receive_data_frame,
            WindowUpdateFrame: self._receive_window_update_frame,
            PingFrame: self._receive_ping_frame,
            RstStreamFrame: self._receive_rst_stream_frame,
            PriorityFrame: self._receive_priority_frame,
        }

    def _prepare_for_sending(self, frames):
        if not frames:
            return
        self._data_to_send += b''.join(f.serialize() for f in frames)
        assert all(f.body_len <= self.max_outbound_frame_size for f in frames)

    @property
    def open_outbound_streams(self):
        """
        The current number of open outbound streams.
        """
        outbound_numbers = int(self.client_side)
        return len(
            [
                stream_id
                for stream_id, stream in self.streams.items()
                if (stream_id % 2 == outbound_numbers) and stream.open
            ]
        )

    @property
    def open_inbound_streams(self):
        """
        The current number of open inbound streams.
        """
        inbound_numbers = int(not self.client_side)
        return len(
            [
                stream_id
                for stream_id, stream in self.streams.items()
                if (stream_id % 2 == inbound_numbers) and stream.open
            ]
        )

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
        s.outbound_flow_control_window = (
            self.remote_settings.initial_window_size
        )
        s.inbound_flow_control_window = self.local_settings.initial_window_size

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

        self._data_to_send += preamble + f.serialize()
        return []

    def get_or_create_stream(self, stream_id):
        """
        Gets a stream by its stream ID. Will create one if one does not already
        exist.
        """
        try:
            return self.streams[stream_id]
        except KeyError:
            return self.begin_new_stream(stream_id)

    def get_stream_by_id(self, stream_id):
        """
        Gets a stream by its stream ID. Raises NoSuchStreamError if the stream
        ID does not correspond to a known stream.
        """
        try:
            return self.streams[stream_id]
        except KeyError:
            raise NoSuchStreamError(stream_id)

    def send_headers(self, stream_id, headers, end_stream=False):
        """
        Send headers on a given stream.
        """
        # Check we can open the stream.
        if stream_id not in self.streams:
            max_open_streams = self.remote_settings.max_concurrent_streams
            if (self.open_outbound_streams + 1) > max_open_streams:
                raise TooManyStreamsError(
                    "Max outbound streams is %d, %d open" %
                    (max_open_streams, self.open_outbound_streams)
                )

        self.state_machine.process_input(ConnectionInputs.SEND_HEADERS)
        stream = self.get_or_create_stream(stream_id)
        frames, events = stream.send_headers(
            headers, self.encoder, end_stream
        )
        self._prepare_for_sending(frames)
        return events

    def send_data(self, stream_id, data, end_stream=False):
        """
        Send data on a given stream.
        """
        if len(data) > self.local_flow_control_window(stream_id):
            raise FlowControlError(
                "Cannot send %d bytes, flow control window is %d." %
                (len(data), self.local_flow_control_window(stream_id))
            )
        elif len(data) > self.max_outbound_frame_size:
            raise FrameTooLargeError(
                "Cannot send frame size %d, max frame size is %d" %
                (len(data), self.max_outbound_frame_size)
            )

        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        frames, events = self.streams[stream_id].send_data(data, end_stream)
        self._prepare_for_sending(frames)

        self.outbound_flow_control_window -= len(data)
        assert self.outbound_flow_control_window >= 0

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
            stream = self.streams[stream_id]
            frames, events = stream.increase_flow_control_window(
                increment
            )
            stream.inbound_flow_control_window += increment
        else:
            f = WindowUpdateFrame(0)
            f.window_increment = increment
            self.inbound_flow_control_window += increment
            frames = [f]
            events = []

        self._prepare_for_sending(frames)
        return events

    def push_stream(self, stream_id, promised_stream_id, request_headers):
        """
        Send a push promise.
        """
        if not self.remote_settings.enable_push:
            raise ProtocolError("Remote peer has disabled stream push")

        self.state_machine.process_input(ConnectionInputs.SEND_PUSH_PROMISE)
        stream = self.get_stream_by_id(stream_id)

        new_stream = self.begin_new_stream(promised_stream_id)
        self.streams[promised_stream_id] = new_stream

        frames, events = stream.push_stream_in_band(
            promised_stream_id, request_headers, self.encoder
        )
        new_frames, new_events = new_stream.locally_pushed()
        self._prepare_for_sending(frames + new_frames)
        return events + new_events

    def ping(self, opaque_data):
        """
        Send a PING frame.

        :param opaque_data: A bytestring of length 8 that will be sent in the
                            PING frame.
        :returns: A list of events.
        """
        if not isinstance(opaque_data, bytes) or len(opaque_data) != 8:
            raise ValueError("Invalid value for ping data: %r" % opaque_data)

        self.state_machine.process_input(ConnectionInputs.SEND_PING)
        f = PingFrame(0)
        f.opaque_data = opaque_data
        self._prepare_for_sending([f])

        return []

    def reset_stream(self, stream_id, error_code=0):
        """
        Reset a stream frame.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_RST_STREAM)
        stream = self.get_stream_by_id(stream_id)
        frames, events = stream.reset_stream(error_code)

        self._prepare_for_sending(frames)
        return events

    def close_connection(self, error_code=0):
        """
        Close a connection, emitting a GOAWAY frame.
        """
        self.state_machine.process_input(ConnectionInputs.SEND_GOAWAY)

        f = GoAwayFrame(0)
        f.error_code = error_code
        f.last_stream_id = self.highest_stream_id
        self._prepare_for_sending([f])

        return []

    def acknowledge_settings(self, event):
        """
        Acknowledge settings that have been received.

        :param event: The RemoteSettingsChanged event that is being
                      acknowledged.
        :returns: A list of events.
        """
        assert isinstance(event, RemoteSettingsChanged)
        self.state_machine.process_input(ConnectionInputs.SEND_SETTINGS)

        changes = self.remote_settings.acknowledge()

        if SettingsFrame.INITIAL_WINDOW_SIZE in changes:
            setting = changes[SettingsFrame.INITIAL_WINDOW_SIZE]
            self._flow_control_change_from_settings(
                setting.original_value,
                setting.new_value,
            )

        # HEADER_TABLE_SIZE changes by the remote part affect our encoder: cf.
        # RFC 7540 Section 6.5.2.
        if SettingsFrame.HEADER_TABLE_SIZE in changes:
            setting = changes[SettingsFrame.HEADER_TABLE_SIZE]
            self.encoder.header_table_size = setting.new_value

        if SettingsFrame.SETTINGS_MAX_FRAME_SIZE in changes:
            setting = changes[SettingsFrame.SETTINGS_MAX_FRAME_SIZE]
            self.max_outbound_frame_size = setting.new_value
            for stream in self.streams.values():
                stream.max_outbound_frame_size = setting.new_value

        f = SettingsFrame(0)
        f.flags.add('ACK')
        self._prepare_for_sending([f])
        return []

    def update_settings(self, new_settings):
        """
        Update the local settings. This will prepare and emit the appropriate
        SETTINGS frame.

        :param new_settings: A dictionary of {setting: new value}
        """
        self.state_machine.process_input(ConnectionInputs.SEND_SETTINGS)
        self.local_settings.update(new_settings)
        s = SettingsFrame(0)
        s.settings = new_settings
        self._prepare_for_sending([s])
        return []

    def local_flow_control_window(self, stream_id):
        """
        Returns the maximum amount of data that can be sent on stream
        ``stream_id``.

        This value will never be larger than the total data that can be sent on
        the connection: even if the given stream allows more data, the
        connection window provides a logical maximum to the amount of data that
        can be sent.

        The maximum data that can be sent in a single data frame on a stream
        is either this value, or the maximum frame size, whichever is
        *smaller*.
        """
        stream = self.get_stream_by_id(stream_id)
        return min(
            self.outbound_flow_control_window,
            stream.outbound_flow_control_window
        )

    def remote_flow_control_window(self, stream_id):
        """
        Returns the maximum amount of data the remote peer can send on stream
        ``stream_id``.

        This value will never be larger than the total data that can be sent on
        the connection: even if the given stream allows more data, the
        connection window provides a logical maximum to the amount of data that
        can be sent.

        The maximum data that can be sent in a single data frame on a stream
        is either this value, or the maximum frame size, whichever is
        *smaller*.
        """
        stream = self.get_stream_by_id(stream_id)
        return min(
            self.inbound_flow_control_window,
            stream.inbound_flow_control_window
        )

    def data_to_send(self, amt=None):
        """
        Returns some data for sending out of the internal data buffer.

        This method is analagous to 'read' on a file-like object, but it
        doesn't block. Instead, it returns as much data as the user asks for,
        or less if that much data is not available. It does not perform any
        I/O, and so uses a different name.
        """
        if amt is None:
            data = self._data_to_send
            self._data_to_send = b''
            return data
        else:
            data = self._data_to_send[:amt]
            self._data_to_send = self._data_to_send[amt:]
            return data

    def clear_outbound_data_buffer(self):
        """
        Clears the outbound data buffer, such that if this call was immediately
        followed by a call to
        :meth:`data_to_send <h2.connection.H2Connection.data_to_send>`, that
        call would return no data.

        This method should not normally be used, but is made available to avoid
        exposing implementation details.
        """
        self._data_to_send = b''

    def _flow_control_change_from_settings(self, old_value, new_value):
        """
        Update flow control windows in response to a change in the value of
        SETTINGS_INITIAL_WINDOW_SIZE.

        When this setting is changed, it automatically updates all flow control
        windows by the delta in the settings values.
        """
        delta = new_value - old_value
        self.outbound_flow_control_window += delta

        for stream in self.streams.values():
            stream.outbound_flow_control_window += delta

        return

    def _inbound_flow_control_change_from_settings(self, old_value, new_value):
        """
        Update remote flow control windows in response to a change in the value
        of SETTINGS_INITIAL_WINDOW_SIZE.

        When this setting is changed, it automatically updates all remote flow
        control windows by the delta in the settings values.
        """
        delta = new_value - old_value
        self.inbound_flow_control_window += delta

        for stream in self.streams.values():
            stream.inbound_flow_control_window += delta

        return

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
        try:
            if frame.body_len > self.max_inbound_frame_size:
                raise ProtocolError(
                    "Received overlong frame: length %d, max %d" %
                    (frame.body_len, self.max_inbound_frame_size)
                )

            # I don't love using __class__ here, maybe reconsider it.
            frames, events = self._frame_dispatch_table[frame.__class__](frame)
        except ProtocolError as e:
            # For whatever reason, receiving the frame caused a protocol error.
            # We should prepare to emit a GoAway frame before throwing the
            # exception up further. No need for an event: the exception will
            # do fine.
            f = GoAwayFrame(0)
            f.last_stream_id = sorted(self.streams.keys())[-1]
            f.error_code = e.error_code
            self.state_machine.process_input(ConnectionInputs.SEND_GOAWAY)
            self._prepare_for_sending([f])
            raise
        else:
            self._prepare_for_sending(frames)

        return events

    def _receive_headers_frame(self, frame):
        """
        Receive a headers frame on the connection.
        """
        # If necessary, check we can open the stream.
        if frame.stream_id not in self.streams:
            max_open_streams = self.local_settings.max_concurrent_streams
            if (self.open_inbound_streams + 1) > max_open_streams:
                raise TooManyStreamsError(
                    "Max outbound streams is %d, %d open" %
                    (max_open_streams, self.open_outbound_streams)
                )

        # Let's decode the headers.
        headers = self.decoder.decode(frame.data)
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_HEADERS
        )
        stream = self.get_or_create_stream(frame.stream_id)
        frames, stream_events = stream.receive_headers(
            headers,
            'END_STREAM' in frame.flags
        )
        return frames, events + stream_events

    def _receive_push_promise_frame(self, frame):
        """
        Receive a push-promise frame on the connection.
        """
        if not self.local_settings.enable_push:
            raise ProtocolError("Received pushed stream")

        pushed_headers = self.decoder.decode(frame.data)

        events = self.state_machine.process_input(
            ConnectionInputs.RECV_PUSH_PROMISE
        )
        stream = self.get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_push_promise_in_band(
            frame.promised_stream_id,
            pushed_headers,
        )

        new_stream = self.begin_new_stream(frame.promised_stream_id)
        self.streams[frame.promised_stream_id] = new_stream
        new_stream.remotely_pushed()

        return frames, events + stream_events

    def _receive_data_frame(self, frame):
        """
        Receive a data frame on the connection.
        """
        if frame.body_len > self.remote_flow_control_window(frame.stream_id):
            raise FlowControlError(
                "Cannot receive %d bytes, flow control window is %d." %
                (
                    frame.body_len,
                    self.remote_flow_control_window(frame.stream_id)
                )
            )

        events = self.state_machine.process_input(
            ConnectionInputs.RECV_DATA
        )
        self.inbound_flow_control_window -= frame.body_len
        stream = self.get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_data(
            frame.data,
            'END_STREAM' in frame.flags,
            frame.body_len
        )
        return frames, events + stream_events

    def _receive_settings_frame(self, frame):
        """
        Receive a SETTINGS frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_SETTINGS
        )

        # This is an ack of the local settings.
        if 'ACK' in frame.flags:
            changed_settings = self._local_settings_acked()
            ack_event = SettingsAcknowledged()
            ack_event.changed_settings = changed_settings
            events.append(ack_event)
            return [], events

        # Add the new settings.
        self.remote_settings.update(frame.settings)

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
            # Increment our local flow control window.
            self.outbound_flow_control_window += frame.window_increment

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
        flags = []

        if 'ACK' in frame.flags:
            evt = PingAcknowledged()
            evt.ping_data = frame.opaque_data
            events.append(evt)
        else:
            f = PingFrame(0)
            f.flags = set(['ACK'])
            f.opaque_data = frame.opaque_data
            flags.append(f)

        return flags, events

    def _receive_rst_stream_frame(self, frame):
        """
        Receive a RST_STREAM frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_RST_STREAM
        )
        stream = self.get_stream_by_id(frame.stream_id)
        stream_frames, stream_events = stream.stream_reset(frame)

        return stream_frames, events + stream_events

    def _receive_priority_frame(self, frame):
        """
        Receive a PRIORITY frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_PRIORITY
        )
        stream = self.get_or_create_stream(frame.stream_id)
        stream_events = stream.priority_changed_remote(frame)

        return [], events + stream_events

    def _local_settings_acked(self):
        """
        Handle the local settings being ACKed, update internal state.
        """
        changes = self.local_settings.acknowledge()

        # HEADER_TABLE_SIZE changes by us affect our decoder: cf.
        # RFC 7540 Section 6.5.2.
        if SettingsFrame.HEADER_TABLE_SIZE in changes:
            setting = changes[SettingsFrame.HEADER_TABLE_SIZE]
            self.decoder.header_table_size = setting.new_value

        if SettingsFrame.INITIAL_WINDOW_SIZE in changes:
            setting = changes[SettingsFrame.INITIAL_WINDOW_SIZE]
            self._inbound_flow_control_change_from_settings(
                setting.original_value,
                setting.new_value,
            )

        return changes

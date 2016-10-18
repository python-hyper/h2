# -*- coding: utf-8 -*-
"""
h2/connection
~~~~~~~~~~~~~

An implementation of a HTTP/2 connection.
"""
from enum import Enum, IntEnum

from hyperframe.exceptions import InvalidPaddingError
from hyperframe.frame import (
    GoAwayFrame, WindowUpdateFrame, HeadersFrame, DataFrame, PingFrame,
    PushPromiseFrame, SettingsFrame, RstStreamFrame, PriorityFrame,
    ContinuationFrame, AltSvcFrame,
)
from hpack.hpack import Encoder, Decoder
from hpack.exceptions import HPACKError

from .errors import PROTOCOL_ERROR, REFUSED_STREAM
from .events import (
    WindowUpdated, RemoteSettingsChanged, PingAcknowledged,
    SettingsAcknowledged, ConnectionTerminated, PriorityUpdated
)
from .exceptions import (
    ProtocolError, NoSuchStreamError, FlowControlError, FrameTooLargeError,
    TooManyStreamsError, StreamClosedError, StreamIDTooLowError,
    NoAvailableStreamIDError, UnsupportedFrameError
)
from .frame_buffer import FrameBuffer
from .settings import (
    Settings, HEADER_TABLE_SIZE, INITIAL_WINDOW_SIZE, MAX_FRAME_SIZE,
    MAX_CONCURRENT_STREAMS
)
from .stream import H2Stream
from .utilities import validate_headers, guard_increment_window


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


class AllowedStreamIDs(IntEnum):
    EVEN = 0
    ODD = 1


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
        (ConnectionState.IDLE, ConnectionInputs.RECV_GOAWAY):
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

        # State: closed
        (ConnectionState.CLOSED, ConnectionInputs.SEND_GOAWAY):
            (None, ConnectionState.CLOSED),
        (ConnectionState.CLOSED, ConnectionInputs.RECV_GOAWAY):
            (None, ConnectionState.CLOSED),
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
                "Invalid input %s in state %s" % (input_, old_state)
            )
        else:
            self.state = target_state
            if func is not None:  # pragma: no cover
                return func()

            return []


class H2Connection(object):
    """
    A low-level HTTP/2 connection object. This handles building and receiving
    frames and maintains both connection and per-stream state for all streams
    on this connection.

    This wraps a HTTP/2 Connection state machine implementation, ensuring that
    frames can only be sent/received when the connection is in a valid state.
    It also builds stream state machines on demand to ensure that the
    constraints of those state machines are met as well. Attempts to create
    frames that cannot be sent will raise a ``ProtocolError``.

    :param client_side: Whether this object is to be used on the client side of
        a connection, or on the server side. Affects the logic used by the
        state machine, the default settings values, the allowable stream IDs,
        and several other properties. Defaults to ``True``.
    :type client_side: ``bool``
    """
    # The initial maximum outbound frame size. This can be changed by receiving
    # a settings frame.
    DEFAULT_MAX_OUTBOUND_FRAME_SIZE = 65535

    # The initial maximum inbound frame size. This is somewhat arbitrarily
    # chosen.
    DEFAULT_MAX_INBOUND_FRAME_SIZE = 2**24

    # The highest acceptable stream ID.
    HIGHEST_ALLOWED_STREAM_ID = 2**31 - 1

    # The largest acceptable window increment.
    MAX_WINDOW_INCREMENT = 2**31 - 1

    def __init__(self, client_side=True):
        self.state_machine = H2ConnectionStateMachine()
        self.streams = {}
        self.highest_inbound_stream_id = 0
        self.highest_outbound_stream_id = 0
        self.encoder = Encoder()
        self.decoder = Decoder()
        self.client_side = client_side

        # Objects that store settings, including defaults.
        #
        # We set the MAX_CONCURRENT_STREAMS value to 100 because its default is
        # unbounded, and that's a dangerous default because it allows
        # essentially unbounded resources to be allocated regardless of how
        # they will be used. 100 should be suitable for the average
        # application. This default obviously does not apply to the remote
        # peer's settings: the remote peer controls them!
        self.local_settings = Settings(
            client=client_side,
            initial_values={MAX_CONCURRENT_STREAMS: 100}
        )
        self.remote_settings = Settings(client=not client_side)

        # The curent value of the connection flow control windows on the
        # connection.
        self.outbound_flow_control_window = (
            self.remote_settings.initial_window_size
        )
        self.inbound_flow_control_window = (
            self.local_settings.initial_window_size
        )

        #: The maximum size of a frame that can be emitted by this peer, in
        #: bytes.
        self.max_outbound_frame_size = self.remote_settings.max_frame_size

        #: The maximum size of a frame that can be received by this peer, in
        #: bytes.
        self.max_inbound_frame_size = self.local_settings.max_frame_size

        # Buffer for incoming data.
        self.incoming_buffer = FrameBuffer(server=not client_side)

        # A private variable to store a sequence of received header frames
        # until completion.
        self._header_frames = []

        # Data that needs to be sent.
        self._data_to_send = b''

        # Keeps track of streams that have been forcefully reset by this peer.
        # Used to ensure that we don't blow up in the face of frames that were
        # in flight when a stream was reset.
        self._reset_streams = set()

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
            GoAwayFrame: self._receive_goaway_frame,
            ContinuationFrame: self._receive_naked_continuation,
            AltSvcFrame: self._receive_frame_noop,
        }

    def _prepare_for_sending(self, frames):
        if not frames:
            return
        self._data_to_send += b''.join(f.serialize() for f in frames)
        assert all(f.body_len <= self.max_outbound_frame_size for f in frames)

    def _open_streams(self, remainder):
        """
        A common method of counting number of open streams. Returns the number
        of streams that are open *and* that have (stream ID % 2) == remainder.
        While it iterates, also deletes any closed streams.
        """
        count = 0
        to_delete = []

        for stream_id, stream in self.streams.items():
            if stream.open and (stream_id % 2 == remainder):
                count += 1
            elif stream.closed:
                to_delete.append(stream_id)

        for stream_id in to_delete:
            del self.streams[stream_id]

        return count

    @property
    def open_outbound_streams(self):
        """
        The current number of open outbound streams.
        """
        outbound_numbers = int(self.client_side)
        return self._open_streams(outbound_numbers)

    @property
    def open_inbound_streams(self):
        """
        The current number of open inbound streams.
        """
        inbound_numbers = int(not self.client_side)
        return self._open_streams(inbound_numbers)

    def _begin_new_stream(self, stream_id, allowed_ids):
        """
        Initiate a new stream.

        .. versionchanged:: 2.0.0
           Removed this function from the public API.

        :param stream_id: The ID of the stream to open.
        :param allowed_ids: What kind of stream ID is allowed.
        """
        outbound = self._stream_id_is_outbound(stream_id)
        highest_stream_id = (
            self.highest_outbound_stream_id if outbound else
            self.highest_inbound_stream_id
        )

        if stream_id <= highest_stream_id:
            raise StreamIDTooLowError(stream_id, highest_stream_id)

        if (stream_id % 2) != int(allowed_ids):
            raise ProtocolError(
                "Invalid stream ID for peer."
            )

        s = H2Stream(stream_id)
        s.max_inbound_frame_size = self.max_inbound_frame_size
        s.max_outbound_frame_size = self.max_outbound_frame_size
        s.outbound_flow_control_window = (
            self.remote_settings.initial_window_size
        )
        s.inbound_flow_control_window = self.local_settings.initial_window_size

        self.streams[stream_id] = s

        if outbound:
            self.highest_outbound_stream_id = stream_id
        else:
            self.highest_inbound_stream_id = stream_id

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

    def _get_or_create_stream(self, stream_id, allowed_ids):
        """
        Gets a stream by its stream ID. Will create one if one does not already
        exist. Use allowed_ids to circumvent the usual stream ID rules for
        clients and servers.

        .. versionchanged:: 2.0.0
           Removed this function from the public API.
        """
        try:
            return self.streams[stream_id]
        except KeyError:
            return self._begin_new_stream(stream_id, allowed_ids)

    def _get_stream_by_id(self, stream_id):
        """
        Gets a stream by its stream ID. Raises NoSuchStreamError if the stream
        ID does not correspond to a known stream and is higher than the current
        maximum: raises if it is lower than the current maximum.

        .. versionchanged:: 2.0.0
           Removed this function from the public API.
        """
        try:
            return self.streams[stream_id]
        except KeyError:
            outbound = self._stream_id_is_outbound(stream_id)
            highest_stream_id = (
                self.highest_outbound_stream_id if outbound else
                self.highest_inbound_stream_id
            )

            if stream_id > highest_stream_id:
                raise NoSuchStreamError(stream_id)
            else:
                raise StreamClosedError(stream_id)

    def get_next_available_stream_id(self):
        """
        Returns an integer suitable for use as the stream ID for the next
        stream created by this endpoint. For server endpoints, this stream ID
        will be even. For client endpoints, this stream ID will be odd. If no
        stream IDs are available, raises :class:`NoAvailableStreamIDError
        <h2.exceptions.NoAvailableStreamIDError>`.

        .. warning:: The return value from this function does not change until
                     the stream ID has actually been used by sending or pushing
                     headers on that stream. For that reason, it should be
                     called as close as possible to the actual use of the
                     stream ID.

        .. versionadded:: 2.0.0

        :raises: :class:`NoAvailableStreamIDError
            <h2.exceptions.NoAvailableStreamIDError>`
        :returns: The next free stream ID this peer can use to initiate a
            stream.
        :rtype: ``int``
        """
        # No streams have been opened yet, so return the lowest allowed stream
        # ID.
        if not self.highest_outbound_stream_id:
            return 1 if self.client_side else 2

        next_stream_id = self.highest_outbound_stream_id + 2
        if next_stream_id > self.HIGHEST_ALLOWED_STREAM_ID:
            raise NoAvailableStreamIDError("Exhausted allowed stream IDs")

        return next_stream_id

    def send_headers(self, stream_id, headers, end_stream=False):
        """
        Send headers on a given stream.

        This function can be used to send request or response headers: the kind
        that are sent depends on whether this connection has been opened as a
        client or server connection, and whether the stream was opened by the
        remote peer or not.

        If this is a client connection, calling ``send_headers`` will send the
        headers as a request. It will also implicitly open the stream being
        used. If this is a client connection and ``send_headers`` has *already*
        been called, this will send trailers instead.

        If this is a server connection, calling ``send_headers`` will send the
        headers as a response. It is a protocol error for a server to open a
        stream by sending headers. If this is a server connection and
        ``send_headers`` has *already* been called, this will send trailers
        instead.

        When acting as a server, you may call ``send_headers`` any number of
        times allowed by the following rules, in this order:

        - zero or more times with ``(':status', '1XX')`` (where ``1XX`` is a
          placeholder for any 100-level status code).
        - once with any other status header.
        - zero or one time for trailers.

        That is, you are allowed to send as many informational responses as you
        like, followed by one complete response and zero or one HTTP trailer
        blocks.

        Clients may send one or two header blocks: one request block, and
        optionally one trailer block.

        .. warning:: In HTTP/2, it is mandatory that all the HTTP/2 special
            headers (that is, ones whose header keys begin with ``:``) appear
            at the start of the header block, before any normal headers.
            If you pass a dictionary to the ``headers`` parameter, it is
            unlikely that they will iterate in that order, and your connection
            may fail. For this reason, passing a ``dict`` to ``headers`` is
            *deprecated*, and will be removed in 3.0.

        :param stream_id: The stream ID to send the headers on. If this stream
            does not currently exist, it will be created.
        :type stream_id: ``int``
        :param headers: The request/response headers to send.
        :type headers: An iterable of two tuples of bytestrings.
        :returns: Nothing
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
        stream = self._get_or_create_stream(
            stream_id, AllowedStreamIDs(self.client_side)
        )
        frames = stream.send_headers(
            headers, self.encoder, end_stream
        )
        self._prepare_for_sending(frames)

    def send_data(self, stream_id, data, end_stream=False):
        """
        Send data on a given stream.

        This method does no breaking up of data: if the data is larger than the
        value returned by :meth:`local_flow_control_window
        <h2.connection.H2Connection.local_flow_control_window>` for this stream
        then a :class:`FlowControlError <h2.exceptions.FlowControlError>` will
        be raised. If the data is larger than :data:`max_outbound_frame_size
        <h2.connection.H2Connection.max_outbound_frame_size>` then a
        :class:`FrameTooLargeError <h2.exceptions.FrameTooLargeError>` will be
        raised.

        Hyper-h2 does this to avoid buffering the data internally. If the user
        has more data to send than hyper-h2 will allow, consider breaking it up
        and buffering it externally.

        :param stream_id: The ID of the stream on which to send the data.
        :type stream_id: ``int``
        :param data: The data to send on the stream.
        :type data: ``bytes``
        :param end_stream: (optional) Whether this is the last data to be sent
            on the stream. Defaults to ``False``.
        :type end_stream: ``bool``
        :returns: Nothing
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
        frames = self.streams[stream_id].send_data(data, end_stream)
        self._prepare_for_sending(frames)

        self.outbound_flow_control_window -= len(data)
        assert self.outbound_flow_control_window >= 0

    def end_stream(self, stream_id):
        """
        Cleanly end a given stream.

        This method ends a stream by sending an empty DATA frame on that stream
        with the ``END_STREAM`` flag set.

        :param stream_id: The ID of the stream to end.
        :type stream_id: ``int``
        :returns: Nothing
        """
        self.state_machine.process_input(ConnectionInputs.SEND_DATA)
        frames = self.streams[stream_id].end_stream()
        self._prepare_for_sending(frames)

    def increment_flow_control_window(self, increment, stream_id=None):
        """
        Increment a flow control window, optionally for a single stream. Allows
        the remote peer to send more data.

        .. versionchanged:: 2.0.0
           Rejects attempts to increment the flow control window by out of
           range values with a ``ValueError``.

        :param increment: The amount ot increment the flow control window by.
        :type increment: ``int``
        :param stream_id: (optional) The ID of the stream that should have its
            flow control window opened. If not present or ``None``, the
            connection flow control window will be opened instead.
        :type stream_id: ``int`` or ``None``
        :returns: Nothing
        :raises: ``ValueError``
        """
        if not (1 <= increment <= self.MAX_WINDOW_INCREMENT):
            raise ValueError(
                "Flow control increment must be between 1 and %d" %
                self.MAX_WINDOW_INCREMENT
            )

        self.state_machine.process_input(ConnectionInputs.SEND_WINDOW_UPDATE)

        if stream_id is not None:
            stream = self.streams[stream_id]
            frames = stream.increase_flow_control_window(
                increment
            )
            stream.inbound_flow_control_window = guard_increment_window(
                stream.inbound_flow_control_window,
                increment
            )
        else:
            f = WindowUpdateFrame(0)
            f.window_increment = increment
            self.inbound_flow_control_window = guard_increment_window(
                self.inbound_flow_control_window,
                increment
            )
            frames = [f]

        self._prepare_for_sending(frames)

    def push_stream(self, stream_id, promised_stream_id, request_headers):
        """
        Push a response to the client by sending a PUSH_PROMISE frame.

        :param stream_id: The ID of the stream that this push is a response to.
        :type stream_id: ``int``
        :param promised_stream_id: The ID of the stream that the pushed
            response will be sent on.
        :type promised_stream_id: ``int``
        :param request_headers: The headers of the request that the pushed
            response will be responding to.
        :type request_headers: An iterable of two tuples of bytestrings.
        :returns: Nothing
        """
        if not self.remote_settings.enable_push:
            raise ProtocolError("Remote peer has disabled stream push")

        self.state_machine.process_input(ConnectionInputs.SEND_PUSH_PROMISE)
        stream = self._get_stream_by_id(stream_id)

        # We need to prevent users pushing streams in response to streams that
        # they themselves have already pushed: see #163 and RFC 7540 § 6.6. The
        # easiest way to do that is to assert that the stream_id is not even:
        # this shortcut works because only servers can push and the state
        # machine will enforce this.
        if (stream_id % 2) == 0:
            raise ProtocolError("Cannot recursively push streams.")

        new_stream = self._begin_new_stream(
            promised_stream_id, AllowedStreamIDs.EVEN
        )
        self.streams[promised_stream_id] = new_stream

        frames = stream.push_stream_in_band(
            promised_stream_id, request_headers, self.encoder
        )
        new_frames = new_stream.locally_pushed()
        self._prepare_for_sending(frames + new_frames)

    def ping(self, opaque_data):
        """
        Send a PING frame.

        :param opaque_data: A bytestring of length 8 that will be sent in the
                            PING frame.
        :returns: Nothing
        """
        if not isinstance(opaque_data, bytes) or len(opaque_data) != 8:
            raise ValueError("Invalid value for ping data: %r" % opaque_data)

        self.state_machine.process_input(ConnectionInputs.SEND_PING)
        f = PingFrame(0)
        f.opaque_data = opaque_data
        self._prepare_for_sending([f])

    def reset_stream(self, stream_id, error_code=0):
        """
        Reset a stream.

        This method forcibly closes a stream by sending a RST_STREAM frame for
        a given stream. This is not a graceful closure. To gracefully end a
        stream, try the :meth:`end_stream
        <h2.connection.H2Connection.end_stream>` method.

        :param stream_id: The ID of the stream to reset.
        :type stream_id: ``int``
        :param error_code: (optional) The error code to use to reset the
            stream. Defaults to :data:`NO_ERROR <h2.errors.NO_ERROR>`.
        :type error_code: ``int``
        :returns: Nothing
        """
        self.state_machine.process_input(ConnectionInputs.SEND_RST_STREAM)
        stream = self._get_stream_by_id(stream_id)
        frames = stream.reset_stream(error_code)
        self._prepare_for_sending(frames)
        self._reset_streams.add(stream_id)
        del self.streams[stream_id]

    def close_connection(self, error_code=0):
        """
        Close a connection, emitting a GOAWAY frame.

        :param error_code: (optional) The error code to send in the GOAWAY
            frame.
        :returns: Nothing
        """
        self.state_machine.process_input(ConnectionInputs.SEND_GOAWAY)

        f = GoAwayFrame(0)
        f.error_code = error_code
        f.last_stream_id = self.highest_inbound_stream_id
        self._prepare_for_sending([f])

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

        :param stream_id: The ID of the stream whose flow control window is
            being queried.
        :type stream_id: ``int``
        :returns: The amount of data in bytes that can be sent on the stream
            before the flow control window is exhausted.
        :rtype: ``int``
        """
        stream = self._get_stream_by_id(stream_id)
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

        :param stream_id: The ID of the stream whose flow control window is
            being queried.
        :type stream_id: ``int``
        :returns: The amount of data in bytes that can be received on the
            stream before the flow control window is exhausted.
        :rtype: ``int``
        """
        stream = self._get_stream_by_id(stream_id)
        return min(
            self.inbound_flow_control_window,
            stream.inbound_flow_control_window
        )

    def data_to_send(self, amt=None):
        """
        Returns some data for sending out of the internal data buffer.

        This method is analagous to ``read`` on a file-like object, but it
        doesn't block. Instead, it returns as much data as the user asks for,
        or less if that much data is not available. It does not perform any
        I/O, and so uses a different name.

        :param amt: (optional) The maximum amount of data to return. If not
            set, or set to ``None``, will return as much data as possible.
        :type amt: ``int``
        :returns: A bytestring containing the data to send on the wire.
        :rtype: ``bytes``
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

    def _acknowledge_settings(self):
        """
        Acknowledge settings that have been received.

        .. versionchanged:: 2.0.0
           Removed from public API, removed useless ``event`` parameter, made
           automatic.

        :returns: Nothing
        """
        self.state_machine.process_input(ConnectionInputs.SEND_SETTINGS)

        changes = self.remote_settings.acknowledge()

        if INITIAL_WINDOW_SIZE in changes:
            setting = changes[INITIAL_WINDOW_SIZE]
            self._flow_control_change_from_settings(
                setting.original_value,
                setting.new_value,
            )

        # HEADER_TABLE_SIZE changes by the remote part affect our encoder: cf.
        # RFC 7540 Section 6.5.2.
        if HEADER_TABLE_SIZE in changes:
            setting = changes[HEADER_TABLE_SIZE]
            self.encoder.header_table_size = setting.new_value

        if MAX_FRAME_SIZE in changes:
            setting = changes[MAX_FRAME_SIZE]
            self.max_outbound_frame_size = setting.new_value
            for stream in self.streams.values():
                stream.max_outbound_frame_size = setting.new_value

        f = SettingsFrame(0)
        f.flags.add('ACK')
        return [f]

    def _flow_control_change_from_settings(self, old_value, new_value):
        """
        Update flow control windows in response to a change in the value of
        SETTINGS_INITIAL_WINDOW_SIZE.

        When this setting is changed, it automatically updates all flow control
        windows by the delta in the settings values. Note that it does not
        increment the *connection* flow control window, per section 6.9.2 of
        RFC 7540.
        """
        delta = new_value - old_value

        for stream in self.streams.values():
            stream.outbound_flow_control_window = guard_increment_window(
                stream.outbound_flow_control_window,
                delta
            )

    def _inbound_flow_control_change_from_settings(self, old_value, new_value):
        """
        Update remote flow control windows in response to a change in the value
        of SETTINGS_INITIAL_WINDOW_SIZE.

        When this setting is changed, it automatically updates all remote flow
        control windows by the delta in the settings values.
        """
        delta = new_value - old_value

        for stream in self.streams.values():
            stream.inbound_flow_control_window += delta

    def receive_data(self, data):
        """
        Pass some received HTTP/2 data to the connection for handling.

        :param data: The data received from the remote peer on the network.
        :type data: ``bytes``
        :returns: A list of events that the remote peer triggered by sending
            this data.
        """
        events = []
        self.incoming_buffer.add_data(data)
        self.incoming_buffer.max_frame_size = self.max_inbound_frame_size

        try:
            for frame in self.incoming_buffer:
                events.extend(self._receive_frame(frame))
        except InvalidPaddingError:
            self._terminate_connection(PROTOCOL_ERROR)
            raise ProtocolError("Received frame with invalid padding.")
        except ProtocolError as e:
            # For whatever reason, receiving the frame caused a protocol error.
            # We should prepare to emit a GoAway frame before throwing the
            # exception up further. No need for an event: the exception will
            # do fine.
            self._terminate_connection(e.error_code)
            raise

        return events

    def _receive_frame(self, frame):
        """
        Handle a frame received on the connection.

        .. versionchanged:: 2.0.0
           Removed from the public API.
        """
        try:
            # I don't love using __class__ here, maybe reconsider it.
            frames, events = self._frame_dispatch_table[frame.__class__](frame)
        except StreamClosedError as e:
            # We need to send a RST_STREAM frame on behalf of the stream.
            # The frame the stream wants to emit is already present in the
            # exception.
            # This does not require re-raising: it's an expected behaviour. The
            # only time we don't do that is if this is a stream the user
            # manually reset.
            if frame.stream_id not in self._reset_streams:
                f = RstStreamFrame(e.stream_id)
                f.error_code = e.error_code
                self._prepare_for_sending([f])
                events = e._events
            else:
                events = []
        except StreamIDTooLowError as e:
            # The stream ID seems invalid. This is unlikely, so it's probably
            # the case that this frame is actually for a stream that we've
            # already reset and removed the state for. If it is, just swallow
            # the error. If we didn't do that, re-raise.
            if frame.stream_id not in self._reset_streams:
                raise
            events = []
        except KeyError as e:  # pragma: no cover
            # We don't have a function for handling this frame. Let's call this
            # a PROTOCOL_ERROR and exit.
            raise UnsupportedFrameError("Unexpected frame: %s" % frame)
        else:
            self._prepare_for_sending(frames)

        return events

    def _terminate_connection(self, error_code):
        """
        Terminate the connection early. Used in error handling blocks to send
        GOAWAY frames.
        """
        f = GoAwayFrame(0)
        f.last_stream_id = self.highest_inbound_stream_id
        f.error_code = error_code
        self.state_machine.process_input(ConnectionInputs.SEND_GOAWAY)
        self._prepare_for_sending([f])

    def _receive_frame_noop(self, frame):
        """
        Receive a frame, but do nothing.
        """
        return [], []

    def _receive_headers_frame(self, frame):
        """
        Receive a headers frame on the connection.
        """
        # If necessary, check we can open the stream. Also validate that the
        # stream ID is valid.
        if frame.stream_id not in self.streams:
            max_open_streams = self.local_settings.max_concurrent_streams
            if (self.open_inbound_streams + 1) > max_open_streams:
                raise TooManyStreamsError(
                    "Max outbound streams is %d, %d open" %
                    (max_open_streams, self.open_outbound_streams)
                )

        # Let's decode the headers.
        try:
            headers = self.decoder.decode(frame.data)
        except (HPACKError, IndexError, TypeError, UnicodeDecodeError) as e:
            # We should only need HPACKError here, but versions of HPACK
            # older than 2.1.0 throw all three others as well. For maximum
            # compatibility, catch all of them.
            raise ProtocolError("Error decoding header block: %s" % e)

        headers = validate_headers(headers)
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_HEADERS
        )
        stream = self._get_or_create_stream(
            frame.stream_id, AllowedStreamIDs(not self.client_side)
        )
        frames, stream_events = stream.receive_headers(
            headers,
            'END_STREAM' in frame.flags
        )

        if 'PRIORITY' in frame.flags:
            p_frames, p_events = self._receive_priority_frame(frame)
            stream_events.extend(p_events)
            assert not p_frames

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

        try:
            stream = self._get_stream_by_id(frame.stream_id)
        except NoSuchStreamError:
            # We need to check if the parent stream was reset by us. If it was
            # then we presume that the PUSH_PROMISE was in flight when we reset
            # the parent stream. Rather than accept the new stream, just reset
            # it.
            #
            # If this was closed naturally, however, we should call this a
            # PROTOCOL_ERROR: pushing a stream on a naturally closed stream is
            # a real problem because it creates a brand new stream that the
            # remote peer now believes exists.
            if frame.stream_id in self._reset_streams:
                f = RstStreamFrame(frame.promised_stream_id)
                f.error_code = REFUSED_STREAM
                return [f], events

            raise ProtocolError("Attempted to push on closed stream.")

        # We need to prevent peers pushing streams in response to streams that
        # they themselves have already pushed: see #163 and RFC 7540 § 6.6. The
        # easiest way to do that is to assert that the stream_id is not even:
        # this shortcut works because only servers can push and the state
        # machine will enforce this.
        if (frame.stream_id % 2) == 0:
            raise ProtocolError("Cannot recursively push streams.")

        frames, stream_events = stream.receive_push_promise_in_band(
            frame.promised_stream_id,
            pushed_headers,
        )

        new_stream = self._begin_new_stream(
            frame.promised_stream_id, AllowedStreamIDs.EVEN
        )
        self.streams[frame.promised_stream_id] = new_stream
        new_stream.remotely_pushed()

        return frames, events + stream_events

    def _receive_data_frame(self, frame):
        """
        Receive a data frame on the connection.
        """
        flow_controlled_length = frame.flow_controlled_length

        try:
            window_size = self.remote_flow_control_window(frame.stream_id)
        except NoSuchStreamError:
            # If the stream doesn't exist we still want to adjust the
            # connection-level flow control window to keep parity with the
            # remote peer. If it does exist we'll adjust it later.
            self.inbound_flow_control_window -= flow_controlled_length
            raise

        if flow_controlled_length > window_size:
            raise FlowControlError(
                "Cannot receive %d bytes, flow control window is %d." %
                (
                    flow_controlled_length,
                    window_size
                )
            )

        events = self.state_machine.process_input(
            ConnectionInputs.RECV_DATA
        )
        self.inbound_flow_control_window -= flow_controlled_length
        stream = self._get_stream_by_id(frame.stream_id)
        frames, stream_events = stream.receive_data(
            frame.data,
            'END_STREAM' in frame.flags,
            flow_controlled_length
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
        events.append(
            RemoteSettingsChanged.from_settings(
                self.remote_settings, frame.settings
            )
        )
        frames = self._acknowledge_settings()

        return frames, events

    def _receive_window_update_frame(self, frame):
        """
        Receive a WINDOW_UPDATE frame on the connection.
        """
        # Validate the frame.
        if not (1 <= frame.window_increment <= self.MAX_WINDOW_INCREMENT):
            raise ProtocolError(
                "Flow control increment must be between 1 and %d, received %d"
                % (self.MAX_WINDOW_INCREMENT, frame.window_increment)
            )

        events = self.state_machine.process_input(
            ConnectionInputs.RECV_WINDOW_UPDATE
        )

        if frame.stream_id:
            stream = self._get_stream_by_id(frame.stream_id)
            frames, stream_events = stream.receive_window_update(
                frame.window_increment
            )
        else:
            # Increment our local flow control window.
            self.outbound_flow_control_window = guard_increment_window(
                self.outbound_flow_control_window,
                frame.window_increment
            )

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
        try:
            stream = self._get_stream_by_id(frame.stream_id)
        except NoSuchStreamError:
            # The stream is missing. That's ok, we just do nothing here.
            stream_frames = []
            stream_events = []
        else:
            stream_frames, stream_events = stream.stream_reset(frame)

        return stream_frames, events + stream_events

    def _receive_priority_frame(self, frame):
        """
        Receive a PRIORITY frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_PRIORITY
        )

        event = PriorityUpdated()
        event.stream_id = frame.stream_id
        event.depends_on = frame.depends_on
        event.exclusive = frame.exclusive

        # Weight is an integer between 1 and 256, but the byte only allows
        # 0 to 255: add one.
        event.weight = frame.stream_weight + 1

        # A stream may not depend on itself.
        if event.depends_on == frame.stream_id:
            raise ProtocolError(
                "Stream %d may not depend on itself" % frame.stream_id
            )
        events.append(event)

        return [], events

    def _receive_goaway_frame(self, frame):
        """
        Receive a GOAWAY frame on the connection.
        """
        events = self.state_machine.process_input(
            ConnectionInputs.RECV_GOAWAY
        )

        # Clear the outbound data buffer: we cannot send further data now.
        self.clear_outbound_data_buffer()

        # Fire an appropriate ConnectionTerminated event.
        new_event = ConnectionTerminated()
        new_event.error_code = frame.error_code
        new_event.last_stream_id = frame.last_stream_id
        new_event.additional_data = (frame.additional_data
                                     if frame.additional_data else None)
        events.append(new_event)

        return [], events

    def _receive_naked_continuation(self, frame):
        """
        A naked CONTINUATION frame has been received. This is always an error,
        but the type of error it is depends on the state of the stream and must
        transition the state of the stream, so we need to pass it to the
        appropriate stream.
        """
        stream = self._get_stream_by_id(frame.stream_id)
        stream.receive_continuation()
        assert False, "Should not be reachable"

    def _local_settings_acked(self):
        """
        Handle the local settings being ACKed, update internal state.
        """
        changes = self.local_settings.acknowledge()

        if INITIAL_WINDOW_SIZE in changes:
            setting = changes[INITIAL_WINDOW_SIZE]
            self._inbound_flow_control_change_from_settings(
                setting.original_value,
                setting.new_value,
            )

        if MAX_FRAME_SIZE in changes:
            setting = changes[MAX_FRAME_SIZE]
            self.max_inbound_frame_size = setting.new_value

        return changes

    def _stream_id_is_outbound(self, stream_id):
        """
        Returns ``True`` if the stream ID corresponds to an outbound stream
        (one initiated by this peer), returns ``False`` otherwise.
        """
        return (stream_id % 2 == int(self.client_side))

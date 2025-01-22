"""
h2/events
~~~~~~~~~

Defines Event types for HTTP/2.

Events are returned by the H2 state machine to allow implementations to keep
track of events triggered by receiving data. Each time data is provided to the
H2 state machine it processes the data and returns a list of Event objects.
"""
import binascii

from hpack import HeaderTuple
from hyperframe.frame import Frame

from .errors import ErrorCodes
from .settings import SettingCodes, Settings, ChangedSetting, _setting_code_from_int

from typing import Union, Optional


class Event:
    """
    Base class for h2 events.
    """
    pass


class RequestReceived(Event):
    """
    The RequestReceived event is fired whenever all of a request's headers
    are received. This event carries the HTTP headers for the given request
    and the stream ID of the new stream.
    
    In HTTP/2, headers may be sent as a HEADERS frame followed by zero or more
    CONTINUATION frames with the final frame setting the END_HEADERS flag.
    This event is fired after the entire sequence is received.

    .. versionchanged:: 2.3.0
       Changed the type of ``headers`` to :class:`HeaderTuple
       <hpack:hpack.HeaderTuple>`. This has no effect on current users.

    .. versionchanged:: 2.4.0
       Added ``stream_ended`` and ``priority_updated`` properties.
    """
    def __init__(self) -> None:
        #: The Stream ID for the stream this request was made on.
        self.stream_id: Optional[int] = None

        #: The request headers.
        self.headers: Optional[list[HeaderTuple]] = None

        #: If this request also ended the stream, the associated
        #: :class:`StreamEnded <h2.events.StreamEnded>` event will be available
        #: here.
        #:
        #: .. versionadded:: 2.4.0
        self.stream_ended: Optional[StreamEnded] = None

        #: If this request also had associated priority information, the
        #: associated :class:`PriorityUpdated <h2.events.PriorityUpdated>`
        #: event will be available here.
        #:
        #: .. versionadded:: 2.4.0
        self.priority_updated: Optional[PriorityUpdated] = None

    def __repr__(self) -> str:
        return "<RequestReceived stream_id:%s, headers:%s>" % (
            self.stream_id, self.headers
        )


class ResponseReceived(Event):
    """
    The ResponseReceived event is fired whenever response headers are received.
    This event carries the HTTP headers for the given response and the stream
    ID of the new stream.

    .. versionchanged:: 2.3.0
       Changed the type of ``headers`` to :class:`HeaderTuple
       <hpack:hpack.HeaderTuple>`. This has no effect on current users.

   .. versionchanged:: 2.4.0
      Added ``stream_ended`` and ``priority_updated`` properties.
    """
    def __init__(self) -> None:
        #: The Stream ID for the stream this response was made on.
        self.stream_id: Optional[int] = None

        #: The response headers.
        self.headers: Optional[list[HeaderTuple]] = None

        #: If this response also ended the stream, the associated
        #: :class:`StreamEnded <h2.events.StreamEnded>` event will be available
        #: here.
        #:
        #: .. versionadded:: 2.4.0
        self.stream_ended: Optional[StreamEnded] = None

        #: If this response also had associated priority information, the
        #: associated :class:`PriorityUpdated <h2.events.PriorityUpdated>`
        #: event will be available here.
        #:
        #: .. versionadded:: 2.4.0
        self.priority_updated: Optional[PriorityUpdated] = None

    def __repr__(self) -> str:
        return "<ResponseReceived stream_id:%s, headers:%s>" % (
            self.stream_id, self.headers
        )


class TrailersReceived(Event):
    """
    The TrailersReceived event is fired whenever trailers are received on a
    stream. Trailers are a set of headers sent after the body of the
    request/response, and are used to provide information that wasn't known
    ahead of time (e.g. content-length). This event carries the HTTP header
    fields that form the trailers and the stream ID of the stream on which they
    were received.

    .. versionchanged:: 2.3.0
       Changed the type of ``headers`` to :class:`HeaderTuple
       <hpack:hpack.HeaderTuple>`. This has no effect on current users.

    .. versionchanged:: 2.4.0
       Added ``stream_ended`` and ``priority_updated`` properties.
    """
    def __init__(self) -> None:
        #: The Stream ID for the stream on which these trailers were received.
        self.stream_id: Optional[int] = None

        #: The trailers themselves.
        self.headers: Optional[list[HeaderTuple]] = None

        #: Trailers always end streams. This property has the associated
        #: :class:`StreamEnded <h2.events.StreamEnded>` in it.
        #:
        #: .. versionadded:: 2.4.0
        self.stream_ended: Optional[StreamEnded] = None

        #: If the trailers also set associated priority information, the
        #: associated :class:`PriorityUpdated <h2.events.PriorityUpdated>`
        #: event will be available here.
        #:
        #: .. versionadded:: 2.4.0
        self.priority_updated: Optional[PriorityUpdated] = None

    def __repr__(self) -> str:
        return "<TrailersReceived stream_id:%s, headers:%s>" % (
            self.stream_id, self.headers
        )


class _HeadersSent(Event):
    """
    The _HeadersSent event is fired whenever headers are sent.

    This is an internal event, used to determine validation steps on
    outgoing header blocks.
    """
    pass


class _ResponseSent(_HeadersSent):
    """
    The _ResponseSent event is fired whenever response headers are sent
    on a stream.

    This is an internal event, used to determine validation steps on
    outgoing header blocks.
    """
    pass


class _RequestSent(_HeadersSent):
    """
    The _RequestSent event is fired whenever request headers are sent
    on a stream.

    This is an internal event, used to determine validation steps on
    outgoing header blocks.
    """
    pass


class _TrailersSent(_HeadersSent):
    """
    The _TrailersSent event is fired whenever trailers are sent on a
    stream. Trailers are a set of headers sent after the body of the
    request/response, and are used to provide information that wasn't known
    ahead of time (e.g. content-length).

    This is an internal event, used to determine validation steps on
    outgoing header blocks.
    """
    pass


class _PushedRequestSent(_HeadersSent):
    """
    The _PushedRequestSent event is fired whenever pushed request headers are
    sent.

    This is an internal event, used to determine validation steps on outgoing
    header blocks.
    """
    pass


class InformationalResponseReceived(Event):
    """
    The InformationalResponseReceived event is fired when an informational
    response (that is, one whose status code is a 1XX code) is received from
    the remote peer.

    The remote peer may send any number of these, from zero upwards. These
    responses are most commonly sent in response to requests that have the
    ``expect: 100-continue`` header field present. Most users can safely
    ignore this event unless you are intending to use the
    ``expect: 100-continue`` flow, or are for any reason expecting a different
    1XX status code.

    .. versionadded:: 2.2.0

    .. versionchanged:: 2.3.0
       Changed the type of ``headers`` to :class:`HeaderTuple
       <hpack:hpack.HeaderTuple>`. This has no effect on current users.

    .. versionchanged:: 2.4.0
       Added ``priority_updated`` property.
    """
    def __init__(self) -> None:
        #: The Stream ID for the stream this informational response was made
        #: on.
        self.stream_id: Optional[int] = None

        #: The headers for this informational response.
        self.headers: Optional[list[HeaderTuple]] = None

        #: If this response also had associated priority information, the
        #: associated :class:`PriorityUpdated <h2.events.PriorityUpdated>`
        #: event will be available here.
        #:
        #: .. versionadded:: 2.4.0
        self.priority_updated: Optional[PriorityUpdated] = None

    def __repr__(self) -> str:
        return "<InformationalResponseReceived stream_id:%s, headers:%s>" % (
            self.stream_id, self.headers
        )


class DataReceived(Event):
    """
    The DataReceived event is fired whenever data is received on a stream from
    the remote peer. The event carries the data itself, and the stream ID on
    which the data was received.

    .. versionchanged:: 2.4.0
       Added ``stream_ended`` property.
    """
    def __init__(self) -> None:
        #: The Stream ID for the stream this data was received on.
        self.stream_id: Optional[int] = None

        #: The data itself.
        self.data: Optional[bytes] = None

        #: The amount of data received that counts against the flow control
        #: window. Note that padding counts against the flow control window, so
        #: when adjusting flow control you should always use this field rather
        #: than ``len(data)``.
        self.flow_controlled_length: Optional[int] = None

        #: If this data chunk also completed the stream, the associated
        #: :class:`StreamEnded <h2.events.StreamEnded>` event will be available
        #: here.
        #:
        #: .. versionadded:: 2.4.0
        self.stream_ended: Optional[StreamEnded] = None

    def __repr__(self) -> str:
        return (
            "<DataReceived stream_id:%s, "
            "flow_controlled_length:%s, "
            "data:%s>" % (
                self.stream_id,
                self.flow_controlled_length,
                _bytes_representation(self.data[:20]) if self.data else "",
            )
        )


class WindowUpdated(Event):
    """
    The WindowUpdated event is fired whenever a flow control window changes
    size. HTTP/2 defines flow control windows for connections and streams: this
    event fires for both connections and streams. The event carries the ID of
    the stream to which it applies (set to zero if the window update applies to
    the connection), and the delta in the window size.
    """
    def __init__(self) -> None:
        #: The Stream ID of the stream whose flow control window was changed.
        #: May be ``0`` if the connection window was changed.
        self.stream_id: Optional[int] = None

        #: The window delta.
        self.delta: Optional[int] = None

    def __repr__(self) -> str:
        return "<WindowUpdated stream_id:%s, delta:%s>" % (
            self.stream_id, self.delta
        )


class RemoteSettingsChanged(Event):
    """
    The RemoteSettingsChanged event is fired whenever the remote peer changes
    its settings. It contains a complete inventory of changed settings,
    including their previous values.

    In HTTP/2, settings changes need to be acknowledged. h2 automatically
    acknowledges settings changes for efficiency. However, it is possible that
    the caller may not be happy with the changed setting.

    When this event is received, the caller should confirm that the new
    settings are acceptable. If they are not acceptable, the user should close
    the connection with the error code :data:`PROTOCOL_ERROR
    <h2.errors.ErrorCodes.PROTOCOL_ERROR>`.

    .. versionchanged:: 2.0.0
       Prior to this version the user needed to acknowledge settings changes.
       This is no longer the case: h2 now automatically acknowledges
       them.
    """
    def __init__(self) -> None:
        #: A dictionary of setting byte to
        #: :class:`ChangedSetting <h2.settings.ChangedSetting>`, representing
        #: the changed settings.
        self.changed_settings: dict[int, ChangedSetting] = {}

    @classmethod
    def from_settings(cls,
                      old_settings: Union[Settings, dict[int, int]],
                      new_settings: dict[int, int]) -> "RemoteSettingsChanged":
        """
        Build a RemoteSettingsChanged event from a set of changed settings.

        :param old_settings: A complete collection of old settings, in the form
                             of a dictionary of ``{setting: value}``.
        :param new_settings: All the changed settings and their new values, in
                             the form of a dictionary of ``{setting: value}``.
        """
        e = cls()
        for setting, new_value in new_settings.items():
            setting = _setting_code_from_int(setting)
            original_value = old_settings.get(setting)
            change = ChangedSetting(setting, original_value, new_value)
            e.changed_settings[setting] = change

        return e

    def __repr__(self) -> str:
        return "<RemoteSettingsChanged changed_settings:{%s}>" % (
            ", ".join(repr(cs) for cs in self.changed_settings.values()),
        )


class PingReceived(Event):
    """
    The PingReceived event is fired whenever a PING is received. It contains
    the 'opaque data' of the PING frame. A ping acknowledgment with the same
    'opaque data' is automatically emitted after receiving a ping.

    .. versionadded:: 3.1.0
    """
    def __init__(self) -> None:
        #: The data included on the ping.
        self.ping_data: Optional[bytes] = None

    def __repr__(self) -> str:
        return "<PingReceived ping_data:%s>" % (
            _bytes_representation(self.ping_data),
        )


class PingAckReceived(Event):
    """
    The PingAckReceived event is fired whenever a PING acknowledgment is
    received. It contains the 'opaque data' of the PING+ACK frame, allowing the
    user to correlate PINGs and calculate RTT.

    .. versionadded:: 3.1.0

    .. versionchanged:: 4.0.0
       Removed deprecated but equivalent ``PingAcknowledged``.
    """
    def __init__(self) -> None:
        #: The data included on the ping.
        self.ping_data: Optional[bytes] = None

    def __repr__(self) -> str:
        return "<PingAckReceived ping_data:%s>" % (
            _bytes_representation(self.ping_data),
        )


class StreamEnded(Event):
    """
    The StreamEnded event is fired whenever a stream is ended by a remote
    party. The stream may not be fully closed if it has not been closed
    locally, but no further data or headers should be expected on that stream.
    """
    def __init__(self) -> None:
        #: The Stream ID of the stream that was closed.
        self.stream_id: Optional[int] = None

    def __repr__(self) -> str:
        return "<StreamEnded stream_id:%s>" % self.stream_id


class StreamReset(Event):
    """
    The StreamReset event is fired in two situations. The first is when the
    remote party forcefully resets the stream. The second is when the remote
    party has made a protocol error which only affects a single stream. In this
    case, h2 will terminate the stream early and return this event.

    .. versionchanged:: 2.0.0
       This event is now fired when h2 automatically resets a stream.
    """
    def __init__(self) -> None:
        #: The Stream ID of the stream that was reset.
        self.stream_id: Optional[int] = None

        #: The error code given. Either one of :class:`ErrorCodes
        #: <h2.errors.ErrorCodes>` or ``int``
        self.error_code: Optional[ErrorCodes] = None

        #: Whether the remote peer sent a RST_STREAM or we did.
        self.remote_reset = True

    def __repr__(self) -> str:
        return "<StreamReset stream_id:%s, error_code:%s, remote_reset:%s>" % (
            self.stream_id, self.error_code, self.remote_reset
        )


class PushedStreamReceived(Event):
    """
    The PushedStreamReceived event is fired whenever a pushed stream has been
    received from a remote peer. The event carries on it the new stream ID, the
    ID of the parent stream, and the request headers pushed by the remote peer.
    """
    def __init__(self) -> None:
        #: The Stream ID of the stream created by the push.
        self.pushed_stream_id: Optional[int] = None

        #: The Stream ID of the stream that the push is related to.
        self.parent_stream_id: Optional[int] = None

        #: The request headers, sent by the remote party in the push.
        self.headers: Optional[list[HeaderTuple]] = None

    def __repr__(self) -> str:
        return (
            "<PushedStreamReceived pushed_stream_id:%s, parent_stream_id:%s, "
            "headers:%s>" % (
                self.pushed_stream_id,
                self.parent_stream_id,
                self.headers,
            )
        )


class SettingsAcknowledged(Event):
    """
    The SettingsAcknowledged event is fired whenever a settings ACK is received
    from the remote peer. The event carries on it the settings that were
    acknowedged, in the same format as
    :class:`h2.events.RemoteSettingsChanged`.
    """
    def __init__(self) -> None:
        #: A dictionary of setting byte to
        #: :class:`ChangedSetting <h2.settings.ChangedSetting>`, representing
        #: the changed settings.
        self.changed_settings: dict[Union[SettingCodes, int], ChangedSetting] = {}

    def __repr__(self) -> str:
        return "<SettingsAcknowledged changed_settings:{%s}>" % (
            ", ".join(repr(cs) for cs in self.changed_settings.values()),
        )


class PriorityUpdated(Event):
    """
    The PriorityUpdated event is fired whenever a stream sends updated priority
    information. This can occur when the stream is opened, or at any time
    during the stream lifetime.

    This event is purely advisory, and does not need to be acted on.

    .. versionadded:: 2.0.0
    """
    def __init__(self) -> None:
        #: The ID of the stream whose priority information is being updated.
        self.stream_id: Optional[int] = None

        #: The new stream weight. May be the same as the original stream
        #: weight. An integer between 1 and 256.
        self.weight: Optional[int] = None

        #: The stream ID this stream now depends on. May be ``0``.
        self.depends_on: Optional[int] = None

        #: Whether the stream *exclusively* depends on the parent stream. If it
        #: does, this stream should inherit the current children of its new
        #: parent.
        self.exclusive: Optional[bool] = None

    def __repr__(self) -> str:
        return (
            "<PriorityUpdated stream_id:%s, weight:%s, depends_on:%s, "
            "exclusive:%s>" % (
                self.stream_id,
                self.weight,
                self.depends_on,
                self.exclusive
            )
        )


class ConnectionTerminated(Event):
    """
    The ConnectionTerminated event is fired when a connection is torn down by
    the remote peer using a GOAWAY frame. Once received, no further action may
    be taken on the connection: a new connection must be established.
    """
    def __init__(self) -> None:
        #: The error code cited when tearing down the connection. Should be
        #: one of :class:`ErrorCodes <h2.errors.ErrorCodes>`, but may not be if
        #: unknown HTTP/2 extensions are being used.
        self.error_code: Optional[Union[ErrorCodes, int]] = None

        #: The stream ID of the last stream the remote peer saw. This can
        #: provide an indication of what data, if any, never reached the remote
        #: peer and so can safely be resent.
        self.last_stream_id: Optional[int] = None

        #: Additional debug data that can be appended to GOAWAY frame.
        self.additional_data: Optional[bytes] = None

    def __repr__(self) -> str:
        return (
            "<ConnectionTerminated error_code:%s, last_stream_id:%s, "
            "additional_data:%s>" % (
                self.error_code,
                self.last_stream_id,
                _bytes_representation(
                    self.additional_data[:20]
                    if self.additional_data else None)
            )
        )


class AlternativeServiceAvailable(Event):
    """
    The AlternativeServiceAvailable event is fired when the remote peer
    advertises an `RFC 7838 <https://tools.ietf.org/html/rfc7838>`_ Alternative
    Service using an ALTSVC frame.

    This event always carries the origin to which the ALTSVC information
    applies. That origin is either supplied by the server directly, or inferred
    by h2 from the ``:authority`` pseudo-header field that was sent by
    the user when initiating a given stream.

    This event also carries what RFC 7838 calls the "Alternative Service Field
    Value", which is formatted like a HTTP header field and contains the
    relevant alternative service information. h2 does not parse or in any
    way modify that information: the user is required to do that.

    This event can only be fired on the client end of a connection.

    .. versionadded:: 2.3.0
    """
    def __init__(self) -> None:
        #: The origin to which the alternative service field value applies.
        #: This field is either supplied by the server directly, or inferred by
        #: h2 from the ``:authority`` pseudo-header field that was sent
        #: by the user when initiating the stream on which the frame was
        #: received.
        self.origin: Optional[bytes] = None

        #: The ALTSVC field value. This contains information about the HTTP
        #: alternative service being advertised by the server. h2 does
        #: not parse this field: it is left exactly as sent by the server. The
        #: structure of the data in this field is given by `RFC 7838 Section 3
        #: <https://tools.ietf.org/html/rfc7838#section-3>`_.
        self.field_value: Optional[bytes] = None

    def __repr__(self) -> str:
        return (
            "<AlternativeServiceAvailable origin:%s, field_value:%s>" % (
                (self.origin or b"").decode('utf-8', 'ignore'),
                (self.field_value or b"").decode('utf-8', 'ignore'),
            )
        )


class UnknownFrameReceived(Event):
    """
    The UnknownFrameReceived event is fired when the remote peer sends a frame
    that h2 does not understand. This occurs primarily when the remote
    peer is employing HTTP/2 extensions that h2 doesn't know anything
    about.

    RFC 7540 requires that HTTP/2 implementations ignore these frames. h2
    does so. However, this event is fired to allow implementations to perform
    special processing on those frames if needed (e.g. if the implementation
    is capable of handling the frame itself).

    .. versionadded:: 2.7.0
    """
    def __init__(self) -> None:
        #: The hyperframe Frame object that encapsulates the received frame.
        self.frame: Optional[Frame] = None

    def __repr__(self) -> str:
        return "<UnknownFrameReceived>"


def _bytes_representation(data: Optional[bytes]) -> Optional[str]:
    """
    Converts a bytestring into something that is safe to print on all Python
    platforms.

    This function is relatively expensive, so it should not be called on the
    mainline of the code. It's safe to use in things like object repr methods
    though.
    """
    if data is None:
        return None

    return binascii.hexlify(data).decode('ascii')

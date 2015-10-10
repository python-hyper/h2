# -*- coding: utf-8 -*-
"""
h2/events
~~~~~~~~~

Defines Event types for HTTP/2.

Events are returned by the H2 state machine to allow implementations to keep
track of events triggered by receiving data. Each time data is provided to the
H2 state machine it processes the data and returns a list of Event objects.
"""
from .settings import ChangedSetting


class RequestReceived(object):
    """
    The RequestReceived event is fired whenever request headers are received.
    This event carries the HTTP headers for the given request and the stream ID
    of the new stream.
    """
    def __init__(self):
        #: The Stream ID for the stream this request was made on.
        self.stream_id = None

        #: The request headers.
        self.headers = None


class ResponseReceived(object):
    """
    The ResponseReceived event is fired whenever request headers are received.
    This event carries the HTTP headers for the given response and the stream
    ID of the new stream.
    """
    def __init__(self):
        #: The Stream ID for the stream this response was made on.
        self.stream_id = None

        #: The response headers.
        self.headers = None


class TrailersReceived(object):
    """
    The TrailersReceived event is fired whenever trailers are received on a
    stream. Trailers are a set of headers sent after the body of the
    request/response, and are used to provide information that wasn't known
    ahead of time (e.g. content-length). This event carries the HTTP header
    fields that form the trailers and the stream ID of the stream on which they
    were received.
    """
    def __init__(self):
        #: The Stream ID for the stream on which these trailers were received.
        self.stream_id = None

        #: The trailers themselves.
        self.headers = None


class DataReceived(object):
    """
    The DataReceived event is fired whenever data is received on a stream from
    the remote peer. The event carries the data itself, and the stream ID on
    which the data was received.
    """
    def __init__(self):
        #: The Stream ID for the stream this data was received on.
        self.stream_id = None

        #: The data itself.
        self.data = None


class WindowUpdated(object):
    """
    The WindowUpdated event is fired whenever a flow control window changes
    size. HTTP/2 defines flow control windows for connections and streams: this
    event fires for both connections and streams. The event carries the ID of
    the stream to which it applies (set to zero if the window update applies to
    the connection), and the delta in the window size.
    """
    def __init__(self):
        #: The Stream ID of the stream whose flow control window was changed.
        #: May be ``0`` if the connection window was changed.
        self.stream_id = None

        #: The window delta.
        self.delta = None


class RemoteSettingsChanged(object):
    """
    The RemoteSettingsChanged event is fired whenever the remote peer changes
    its settings. It contains a complete inventory of changed settings,
    including their previous values.

    In HTTP/2, settings changes need to be acknowledged. hyper-h2 does not
    automatically acknowledge them, because it is possible that the caller may
    not be happy with the changed setting (or would like to know about it).
    When this event is received, the caller should confirm that the new
    settings are acceptable, and then acknowledge them. If they are not
    acceptable, the user should close the connection.
    """
    def __init__(self):
        #: A dictionary of setting byte to
        #: :class:`ChangedSetting <h2.settings.ChangedSetting>`, representing
        #: the changed settings.
        self.changed_settings = {}

    @classmethod
    def from_settings(cls, old_settings, new_settings):
        """
        Build a RemoteSettingsChanged event from a set of changed settings.

        :param old_settings: A complete collection of old settings, in the form
                             of a dictionary of ``{setting: value}``.
        :param new_settings: All the changed settings and their new values, in
                             the form of a dictionary of ``{setting: value}``.
        """
        e = cls()
        for setting, new_value in new_settings.items():
            original_value = old_settings.get(setting)
            change = ChangedSetting(setting, original_value, new_value)
            e.changed_settings[setting] = change

        return e


class PingAcknowledged(object):
    """
    The PingAcknowledged event is fired whenever a user-emitted PING is
    acknowledged. This contains the data in the ACK'ed PING, allowing the
    user to correlate PINGs and calculate RTT.
    """
    def __init__(self):
        #: The data included on the ping.
        self.ping_data = None


class StreamEnded(object):
    """
    The StreamEnded event is fired whenever a stream is ended by a remote
    party. The stream may not be fully closed if it has not been closed
    locally, but no further data or headers should be expected on that stream.
    """
    def __init__(self):
        #: The Stream ID of the stream that was closed.
        self.stream_id = None


class StreamReset(object):
    """
    The StreamReset event is fired whenever a stream is forcefully reset by the
    remote party. When this event is received, no further data can be sent on
    the stream.
    """
    def __init__(self):
        #: The Stream ID of the stream that was reset.
        self.stream_id = None

        #: The error code given.
        self.error_code = None


class PushedStreamReceived(object):
    """
    The PushedStreamReceived event is fired whenever a pushed stream has been
    received from a remote peer. The event carries on it the new stream ID, the
    ID of the parent stream, and the request headers pushed by the remote peer.
    """
    def __init__(self):
        #: The Stream ID of the stream created by the push.
        self.pushed_stream_id = None

        #: The Stream ID of the stream that the push is related to.
        self.parent_stream_id = None

        #: The request headers, sent by the remote party in the push.
        self.headers = None


class SettingsAcknowledged(object):
    """
    The SettingsAcknowledged event is fired whenever a settings ACK is received
    from the remote peer. The event carries on it the settings that were
    acknowedged, in the same format as
    :class:`h2.events.RemoteSettingsChanged`.
    """
    def __init__(self):
        #: A dictionary of setting byte to
        #: :class:`ChangedSetting <h2.settings.ChangedSetting>`, representing
        #: the changed settings.
        self.changed_settings = {}

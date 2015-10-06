# -*- coding: utf-8 -*-
"""
h2/exceptions
~~~~~~~~~~~~~

Exceptions for the HTTP/2 module.
"""


class H2Error(Exception):
    """
    The base class for all exceptions for the HTTP/2 module.
    """


class ProtocolError(H2Error):
    """
    An action was attempted in violation of the HTTP/2 protocol.
    """
    pass


class FrameTooLargeError(ProtocolError):
    """
    The frame that we tried to send was too large to be sent.
    """
    pass


class TooManyStreamsError(ProtocolError):
    """
    An attempt was made to open a stream that would lead to too many concurrent
    streams.
    """
    pass


class NoSuchStreamError(H2Error):
    """
    A stream-specific action referenced a stream that does not exist.
    """
    def __init__(self, stream_id):
        self.stream_id = stream_id


class FlowControlError(H2Error):
    """
    An attempted action violates flow control constraints.
    """
    pass

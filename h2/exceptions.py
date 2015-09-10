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


class NoSuchStreamError(H2Error):
    """
    A stream-specific action referenced a stream that does not exist.
    """
    def __init__(self, stream_id):
        self.stream_id = stream_id

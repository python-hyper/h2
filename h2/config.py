# -*- coding: utf-8 -*-
"""
h2/config
~~~~~~~~~

Objects for controlling the configuration of the HTTP/2 stack.
"""


class H2Configuration(object):
    """
    An object that controlls the way a single HTTP/2 connection behaves.

    This object allows the users to customize behaviour. In particular, it
    allows users to enable or disable optional features, or to otherwise handle
    various unusual behaviours.

    This object has very little behaviour of its own: it mostly just ensures
    that configuration is self-consistent.
    """
    def __init__(self):
        self._client_side = True
        self._header_encoding = 'utf-8'

    @property
    def client_side(self):
        """
        Whether this object is to be used on the client side of a connection,
        or on the server side. Affects the logic used by the state machine, the
        default settings values, the allowable stream IDs, and several other
        properties. Defaults to ``True``.
        """
        return self._client_side

    @client_side.setter
    def client_side(self, value):
        """
        Enforces constraints on the client side of the connection.
        """
        if not isinstance(value, bool):
            raise ValueError("client_side must be a bool")
        self._client_side = value

    @property
    def header_encoding(self):
        """
        Controls whether the headers emitted by this object in events are
        transparently decoded to ``unicode`` strings, and what encoding is used
        to do that decoding. For historical reasons, this defaults to
        ``'utf-8'``. To prevent the decoding of headers (that is, to force them
        to be returned as bytestrings), this can be set to ``False`` or the
        empty string.
        """
        return self._header_encoding

    @header_encoding.setter
    def header_encoding(self, value):
        """
        Enforces constraints on the value of header encoding.
        """
        if not isinstance(value, (bool, str, type(None))):
            raise ValueError("header_encoding must be bool, string, or None")
        if value is True:
            raise ValueError("header_encoding cannot be True")
        self._header_encoding = value

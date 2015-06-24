# -*- coding: utf-8 -*-
"""
h2/exceptions
~~~~~~~~~~~~~

Exceptions for the HTTP/2 module.
"""


class ProtocolError(Exception):
    """
    An action was attempted in violation of the HTTP/2 protocol.
    """
    pass

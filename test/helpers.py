# -*- coding: utf-8 -*-
"""
helpers
~~~~~~~

This module contains helpers for the h2 tests.
"""
from hyperframe.frame import HeadersFrame, DataFrame
from hpack.hpack import Encoder


class FrameFactory(object):
    """
    A class containing lots of helper methods and state to build frames. This
    allows test cases to easily build correct HTTP/2 frames to feed to
    hyper-h2.
    """
    def __init__(self):
        self.encoder = Encoder()

    def preamble(self):
        return b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'

    def build_headers_frame(self, headers, flags=None):
        """
        Builds a single valid headers frame out of the contained headers.
        """
        f = HeadersFrame(1)
        f.data = self.encoder.encode(headers)
        f.flags.add('END_HEADERS')
        if flags:
            f.flags.update(flags)
        return f

    def build_data_frame(self, data, flags=None):
        """
        Builds a single data frame out of a chunk of data.
        """
        flags = set(flags) if flags is not None else set()
        f = DataFrame(1)
        f.data = data
        f.flags = flags
        return f

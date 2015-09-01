# -*- coding: utf-8 -*-
"""
helpers
~~~~~~~

This module contains helpers for the h2 tests.
"""
from hyperframe.frame import HeadersFrame, DataFrame
from hpack.hpack import Encoder


def build_headers_frame(headers, encoder=None):
    """
    Builds a single valid headers frame out of the contained headers.
    """
    f = HeadersFrame(1)
    e = encoder if encoder else Encoder()
    f.data = e.encode(headers)
    f.flags.add('END_HEADERS')
    return f


def build_data_frames(data, flags=None):
    """
    Builds a single data frame out of a chunk of data.
    """
    flags = flags if flags is not None else set()
    f = DataFrame(1)
    f.data = data
    f.flags = flags
    return f

# -*- coding: utf-8 -*-
"""
h2/frame_buffer
~~~~~~~~~~~~~~~

A data structure that provides a way to iterate over a byte buffer in terms of
frames.
"""
from hyperframe.exceptions import UnknownFrameError
from hyperframe.frame import Frame

from .exceptions import ProtocolError


class FrameBuffer(object):
    """
    This is a data structure that expects to act as a buffer for HTTP/2 data
    that allows iteraton in terms of H2 frames.
    """
    def __init__(self, server=False):
        self.data = b''
        self._preamble = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n' if server else b''
        self._preamble_len = len(self._preamble)

    def add_data(self, data):
        """
        Add more data to the frame buffer.

        :param data: A bytestring containing the byte buffer.
        """
        if self._preamble_len:
            data_len = len(data)
            of_which_preamble = min(self._preamble_len, data_len)

            if self._preamble[:of_which_preamble] != data[:of_which_preamble]:
                raise ProtocolError("Invalid HTTP/2 preamble.")

            data = data[of_which_preamble:]
            self._preamble_len -= of_which_preamble
            self._preamble = self._preamble[of_which_preamble:]

        self.data += data

    # The methods below support the iterator protocol.
    def __iter__(self):
        return self

    def next(self):  # Python 2
        if len(self.data) < 9:
            raise StopIteration()

        try:
            f, length = Frame.parse_frame_header(self.data[:9])
        except UnknownFrameError as e:
            # Here we do something a bit odd. We want to consume the frame data
            # as consistently as possible, but we also don't ever want to yield
            # None. Instead, we make sure that, if there is no frame, we
            # recurse into ourselves.
            length = e.length
            f = None

        if len(self.data) < length + 9:
            raise StopIteration()

        if f is not None:
            f.parse_body(memoryview(self.data[9:9+length]))

        self.data = self.data[9+length:]
        return f if f is not None else self.next()

    def __next__(self):  # Python 3
        return self.next()

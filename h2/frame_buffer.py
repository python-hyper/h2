# -*- coding: utf-8 -*-
"""
h2/frame_buffer
~~~~~~~~~~~~~~~

A data structure that provides a way to iterate over a byte buffer in terms of
frames.
"""
from hyperframe.frame import Frame


class FrameBuffer(object):
    """
    This is a data structure that expects to act as a buffer for HTTP/2 data
    that allows iteraton in terms of H2 frames.
    """
    def __init__(self, server=False):
        self.data = b''
        self.preamble_len = (
            len(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n') if server else 0
        )

    def add_data(self, data):
        """
        Add more data to the frame buffer.

        :param data: A bytestring containing the byte buffer.
        """
        if self.preamble_len:
            data_len = len(data)
            data = data[self.preamble_len:]
            self.preamble_len -= min(data_len, self.preamble_len)

        self.data += data

    def __iter__(self):
        return self

    def next(self):
        if len(self.data) < 9:
            raise StopIteration()

        f, length = Frame.parse_frame_header(self.data[:9])
        if len(self.data) < length + 9:
            raise StopIteration()

        f.parse_body(memoryview(self.data[9:9+length]))
        self.data = self.data[9+length:]
        return f

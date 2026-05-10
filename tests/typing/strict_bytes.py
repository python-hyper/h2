from __future__ import annotations

from h2.connection import H2Connection
from h2.frame_buffer import FrameBuffer


def receive_data_accepts_buffer_types(
    connection: H2Connection,
    frame_buffer: FrameBuffer,
) -> None:
    bytearray_data = bytearray(b"")
    memoryview_data = memoryview(b"")

    connection.receive_data(bytearray_data)
    connection.receive_data(memoryview_data)
    frame_buffer.add_data(bytearray_data)
    frame_buffer.add_data(memoryview_data)

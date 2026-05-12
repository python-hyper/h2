from __future__ import annotations

from hyperframe.frame import Frame
from typing_extensions import assert_type

from h2.connection import H2Connection
from h2.events import Event
from h2.frame_buffer import FrameBuffer


def receive_data_accepts_buffer_types() -> None:
    connection = H2Connection()
    frame_buffer = FrameBuffer()
    bytearray_data = bytearray(b"")
    memoryview_data = memoryview(b"")

    bytearray_events = connection.receive_data(bytearray_data)
    memoryview_events = connection.receive_data(memoryview_data)
    frame_buffer.add_data(bytearray_data)
    frame_buffer.add_data(memoryview_data)
    buffered_frames = list(frame_buffer)

    assert_type(bytearray_events, list[Event])
    assert_type(memoryview_events, list[Event])
    assert_type(buffered_frames, list[Frame])
    assert bytearray_events == []
    assert memoryview_events == []
    assert buffered_frames == []

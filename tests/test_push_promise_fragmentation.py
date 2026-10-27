"""Check outbound PUSH_PROMISE fragmentation with a receiving h2 peer."""
from __future__ import annotations

import pytest
from hpack import Encoder
from hyperframe.frame import ContinuationFrame, Frame, PushPromiseFrame

import h2.config
import h2.connection
import h2.events


@pytest.mark.parametrize("value_size", [
    0,      # Small header block.
    26170,  # Encoded block exactly fits alongside the promised stream ID.
    26172,  # Encoded block exceeds the first frame's capacity by one byte.
    26177,  # Encoded block fills a frame without the promised stream ID.
    26178,  # Encoded block exceeds a full frame by one byte.
    53000,  # Multiple CONTINUATION frames.
])
def test_push_promise_respects_frame_size(value_size: int) -> None:
    """Reserve the promised stream ID's four bytes when fragmenting headers."""
    client = h2.connection.H2Connection()
    server = h2.connection.H2Connection(
        config=h2.config.H2Configuration(client_side=False),
    )
    client.initiate_connection()
    server.initiate_connection()
    server.receive_data(client.data_to_send())
    client.receive_data(server.data_to_send())
    server.receive_data(client.data_to_send())

    headers = [
        (b":method", b"GET"),
        (b":scheme", b"https"),
        (b":authority", b"example.com"),
        (b":path", b"/"),
    ]
    client.send_headers(1, headers, end_stream=True)
    server.receive_data(client.data_to_send())
    pushed_headers = [*headers, (b"x-test", b"a" * value_size)]
    encoded_headers = Encoder().encode(pushed_headers)

    server.push_stream(1, 2, pushed_headers)
    data = server.data_to_send()

    frames = []
    remaining = memoryview(data)
    while remaining:
        frame, length = Frame.parse_frame_header(remaining[:9])
        assert length <= client.max_inbound_frame_size
        frame.parse_body(remaining[9:9 + length])
        frames.append(frame)
        remaining = remaining[9 + length:]

    assert isinstance(frames[0], PushPromiseFrame)
    assert frames[0].promised_stream_id == 2
    assert all(isinstance(frame, ContinuationFrame) for frame in frames[1:])
    assert all(frame.stream_id == 1 for frame in frames)
    assert "END_HEADERS" in frames[-1].flags
    assert all("END_HEADERS" not in frame.flags for frame in frames[:-1])
    assert b"".join(frame.data for frame in frames) == encoded_headers

    events = client.receive_data(data)
    assert len(events) == 1
    assert isinstance(events[0], h2.events.PushedStreamReceived)
    assert events[0].pushed_stream_id == 2
    assert events[0].parent_stream_id == 1
    assert events[0].headers == pushed_headers

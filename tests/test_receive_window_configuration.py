"""Wire-level tests for configuring receive windows with automatic flow control."""
from __future__ import annotations

import pytest
from hyperframe.frame import SettingsFrame, WindowUpdateFrame

import h2.config
import h2.connection
import h2.events
import h2.exceptions
import h2.settings

DEFAULT_WINDOW = 65535
CONNECTION_WINDOW = 1024 * 1024
STREAM_WINDOW = 256 * 1024
REQUEST_HEADERS = [
    (":method", "POST"),
    (":scheme", "https"),
    (":authority", "example.com"),
    (":path", "/"),
]


@pytest.fixture(params=[True, False], ids=["client-receiver", "server-receiver"])
def peers(request) -> tuple[h2.connection.H2Connection, h2.connection.H2Connection]:
    """Create client and server peers with either side acting as the receiver."""
    receiver = h2.connection.H2Connection(
        config=h2.config.H2Configuration(client_side=request.param),
    )
    sender = h2.connection.H2Connection(
        config=h2.config.H2Configuration(client_side=not request.param),
    )
    receiver.initiate_connection()
    sender.initiate_connection()
    return receiver, sender


def open_stream(receiver, sender, stream_id=1) -> None:
    """Exchange startup frames and open a stream carrying data to the receiver."""
    receiver.receive_data(sender.data_to_send())
    sender.receive_data(receiver.data_to_send())
    receiver.receive_data(sender.data_to_send())
    if receiver.config.client_side:
        receiver.send_headers(stream_id, REQUEST_HEADERS, end_stream=True)
        sender.receive_data(receiver.data_to_send())
        sender.send_headers(stream_id, [(":status", "200")])
    else:
        sender.send_headers(stream_id, REQUEST_HEADERS)
    receiver.receive_data(sender.data_to_send())


def receive_bytes(receiver, sender, size) -> list[h2.events.DataReceived]:
    """Deliver actual DATA frames, including padding in the flow-controlled size."""
    events = []
    while size:
        chunk_size = min(size, sender.max_outbound_frame_size)
        # One byte for the padding length and one byte of padding.
        sender.send_data(1, b"x" * (chunk_size - 2), pad_length=1)
        events.extend(receiver.receive_data(sender.data_to_send()))
        size -= chunk_size
    assert all(isinstance(event, h2.events.DataReceived) for event in events)
    return events


def window_update(stream_id, increment) -> bytes:
    """Serialize the expected WINDOW_UPDATE independently of the connection."""
    frame = WindowUpdateFrame(stream_id)
    frame.window_increment = increment
    return frame.serialize()


@pytest.mark.parametrize("connection_window", [DEFAULT_WINDOW, CONNECTION_WINDOW])
def test_automatic_replenishment_uses_configured_connection_window(peers, connection_window) -> None:
    """The startup increment changes the ACK threshold and survives repeated rounds."""
    receiver, sender = peers
    if connection_window > DEFAULT_WINDOW:
        receiver.increment_flow_control_window(connection_window - DEFAULT_WINDOW)
    receiver.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: STREAM_WINDOW})
    open_stream(receiver, sender)

    assert sender.outbound_flow_control_window == connection_window
    assert sender.remote_settings.initial_window_size == STREAM_WINDOW
    assert receiver.outbound_flow_control_window == DEFAULT_WINDOW

    # With the default connection window, 32 KiB of ACKs trigger a connection
    # update. With 1 MiB, ACKs are coalesced until 512 KiB has been processed.
    chunk_size = 32768
    rounds = 2 * max(1, connection_window // (2 * chunk_size))
    connection_processed = stream_processed = 0
    for _ in range(rounds):
        events = receive_bytes(receiver, sender, chunk_size)
        assert sum(event.flow_controlled_length for event in events) == chunk_size
        assert not receiver.data_to_send()  # Receipt alone releases no credit.
        for event in events:
            receiver.acknowledge_received_data(event.flow_controlled_length, event.stream_id)

        connection_processed += chunk_size
        stream_processed += chunk_size
        expected = b""
        if connection_processed >= connection_window // 2:
            expected += window_update(0, connection_processed)
            connection_processed = 0
        if stream_processed >= STREAM_WINDOW // 2:
            expected += window_update(1, stream_processed)
            stream_processed = 0
        wire = receiver.data_to_send()
        assert wire == expected
        sender.receive_data(wire)
        assert sender.outbound_flow_control_window == connection_window - connection_processed
        assert receiver.inbound_flow_control_window == connection_window - connection_processed
        assert sender.local_flow_control_window(1) == min(
            connection_window - connection_processed, STREAM_WINDOW - stream_processed,
        )


def test_connection_enlargement_leaves_stream_windows_unchanged(peers) -> None:
    """Only stream zero is updated, even when the connection reaches the RFC limit."""
    receiver, sender = peers
    # Drain the preface separately so the expected bytes are exactly one update.
    sender.receive_data(receiver.data_to_send())
    increment = 2**31 - 1 - DEFAULT_WINDOW
    receiver.increment_flow_control_window(increment)
    wire = receiver.data_to_send()
    assert wire == window_update(0, increment)
    sender.receive_data(wire)
    open_stream(receiver, sender)
    assert sender.outbound_flow_control_window == 2**31 - 1
    assert receiver.inbound_flow_control_window == 2**31 - 1
    assert sender.local_flow_control_window(1) == DEFAULT_WINDOW
    assert sender.remote_settings.initial_window_size == DEFAULT_WINDOW
    assert receiver.outbound_flow_control_window == DEFAULT_WINDOW
    events = receive_bytes(receiver, sender, 32768)
    for event in events:
        receiver.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    assert receiver.data_to_send() == window_update(1, 32768)
    assert receiver.inbound_flow_control_window == 2**31 - 1 - 32768


@pytest.mark.parametrize("stream_window", [0, STREAM_WINDOW, 2**31 - 1])
def test_stream_setting_leaves_connection_window_unchanged(peers, stream_window) -> None:
    """SETTINGS and its ACK affect existing and new streams, never the connection."""
    receiver, sender = peers
    open_stream(receiver, sender)
    receiver.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: stream_window})
    frame = SettingsFrame(0)
    frame.settings[h2.settings.SettingCodes.INITIAL_WINDOW_SIZE] = stream_window
    wire = receiver.data_to_send()
    assert wire == frame.serialize()
    sender.receive_data(wire)
    assert receiver.local_settings.initial_window_size == DEFAULT_WINDOW
    ack = sender.data_to_send()
    frame = SettingsFrame(0)
    frame.flags.add("ACK")
    assert ack == frame.serialize()
    receiver.receive_data(ack)
    assert receiver.local_settings.initial_window_size == stream_window
    assert sender.outbound_flow_control_window == DEFAULT_WINDOW
    assert receiver.inbound_flow_control_window == DEFAULT_WINDOW
    assert sender.local_flow_control_window(1) == min(DEFAULT_WINDOW, stream_window)
    open_stream(receiver, sender, stream_id=3)
    assert sender.local_flow_control_window(3) == min(DEFAULT_WINDOW, stream_window)


def test_increment_after_consumption_may_only_restore_current_window(peers) -> None:
    """Restoring used credit does not increase the automatic replenishment maximum."""
    receiver, sender = peers
    open_stream(receiver, sender)
    events = receive_bytes(receiver, sender, 32768)
    receiver.increment_flow_control_window(32768)
    assert receiver.data_to_send() == window_update(0, 32768)
    # The connection is already full. ACKs update only the depleted stream.
    for event in events:
        receiver.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    assert receiver.data_to_send() == window_update(1, 32768)
    assert receiver.inbound_flow_control_window == DEFAULT_WINDOW


@pytest.mark.parametrize("increment", [-1, 0, 2**31])
def test_invalid_increment_preserves_configured_window(peers, increment) -> None:
    """Out-of-range increments emit no frames and leave valid credit intact."""
    receiver, sender = peers
    receiver.increment_flow_control_window(CONNECTION_WINDOW - DEFAULT_WINDOW)
    open_stream(receiver, sender)
    with pytest.raises(ValueError, match="Flow control increment must be between"):
        receiver.increment_flow_control_window(increment)
    assert not receiver.data_to_send()
    assert receiver.inbound_flow_control_window == CONNECTION_WINDOW


def test_zero_and_negative_acknowledgements_with_enlarged_window(peers) -> None:
    """Zero ACKs release no credit; negative ACKs are rejected without changes."""
    receiver, sender = peers
    receiver.increment_flow_control_window(CONNECTION_WINDOW - DEFAULT_WINDOW)
    open_stream(receiver, sender)
    receive_bytes(receiver, sender, 32768)
    with pytest.raises(ValueError, match="Cannot acknowledge negative data"):
        receiver.acknowledge_received_data(-1, 1)
    receiver.acknowledge_received_data(0, 1)
    assert not receiver.data_to_send()
    assert receiver.inbound_flow_control_window == CONNECTION_WINDOW - 32768
    assert receiver.remote_flow_control_window(1) == DEFAULT_WINDOW - 32768


def test_stream_setting_can_make_available_credit_negative(peers) -> None:
    """A stream decrease can block sending while the connection retains credit."""
    receiver, sender = peers
    receiver.increment_flow_control_window(CONNECTION_WINDOW - DEFAULT_WINDOW)
    open_stream(receiver, sender)
    events = receive_bytes(receiver, sender, 32768)
    receiver.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 16384})
    sender.receive_data(receiver.data_to_send())
    assert sender.local_flow_control_window(1) == -16384
    receiver.receive_data(sender.data_to_send())
    assert receiver.inbound_flow_control_window == CONNECTION_WINDOW - 32768
    with pytest.raises(h2.exceptions.FlowControlError):
        sender.send_data(1, b"x")
    assert not sender.data_to_send()
    for event in events:
        receiver.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    wire = receiver.data_to_send()
    assert wire == window_update(1, 16384) * 2
    sender.receive_data(wire)
    assert sender.local_flow_control_window(1) == 16384
    assert sender.outbound_flow_control_window == CONNECTION_WINDOW - 32768

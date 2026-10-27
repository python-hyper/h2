"""Rejected local SETTINGS updates must not leak into later acknowledgements."""

from __future__ import annotations

import pytest

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.errors import ErrorCodes
from h2.events import RemoteSettingsChanged, SettingsAcknowledged
from h2.exceptions import InvalidSettingsValueError, ProtocolError
from h2.settings import SettingCodes


def connected_peers(client_side: bool) -> tuple[H2Connection, H2Connection]:
    """Complete an actual in-memory HTTP/2 preface and SETTINGS exchange."""
    sender = H2Connection(config=H2Configuration(client_side=client_side))
    peer = H2Connection(config=H2Configuration(client_side=not client_side))
    sender.initiate_connection()
    peer.initiate_connection()
    for _ in range(3):
        for source, target in ((sender, peer), (peer, sender)):
            data = source.data_to_send()
            if data:
                target.receive_data(data)
    return sender, peer


@pytest.mark.parametrize("client_side", [True, False])
@pytest.mark.parametrize(
    ("setting", "value", "error_code"),
    [
        (SettingCodes.ENABLE_PUSH, 2, ErrorCodes.PROTOCOL_ERROR),
        (SettingCodes.INITIAL_WINDOW_SIZE, -1, ErrorCodes.FLOW_CONTROL_ERROR),
        (SettingCodes.MAX_FRAME_SIZE, 16383, ErrorCodes.PROTOCOL_ERROR),
        (SettingCodes.MAX_HEADER_LIST_SIZE, -1, ErrorCodes.PROTOCOL_ERROR),
        (SettingCodes.ENABLE_CONNECT_PROTOCOL, 2, ErrorCodes.PROTOCOL_ERROR),
    ],
)
def test_rejected_batch_does_not_apply_unsent_settings(
    client_side: bool,
    setting: SettingCodes,
    value: int,
    error_code: ErrorCodes,
) -> None:
    """Only values in an emitted SETTINGS frame can become acknowledged."""
    sender, peer = connected_peers(client_side)
    original_limit = sender.local_settings.max_concurrent_streams
    with pytest.raises(InvalidSettingsValueError) as exc:
        sender.update_settings({SettingCodes.MAX_CONCURRENT_STREAMS: 3, setting: value})
    assert exc.value.error_code == error_code
    assert sender.data_to_send() == b""
    assert sender.local_settings.max_concurrent_streams == original_limit

    sender.update_settings({SettingCodes.HEADER_TABLE_SIZE: 1024})
    changes = peer.receive_data(sender.data_to_send())
    assert len(changes) == 1
    assert isinstance(changes[0], RemoteSettingsChanged)
    assert set(changes[0].changed_settings) == {SettingCodes.HEADER_TABLE_SIZE}
    acknowledgements = sender.receive_data(peer.data_to_send())
    assert len(acknowledgements) == 1
    assert isinstance(acknowledgements[0], SettingsAcknowledged)
    assert set(acknowledgements[0].changed_settings) == {SettingCodes.HEADER_TABLE_SIZE}
    assert sender.local_settings.max_concurrent_streams == peer.remote_settings.max_concurrent_streams == original_limit
    assert sender.local_settings.header_table_size == peer.remote_settings.header_table_size == 1024


@pytest.mark.parametrize("client_side", [True, False])
def test_rejected_batch_preserves_pending_settings(client_side: bool) -> None:
    """A rejected value must not follow a legitimately pending value."""
    sender, peer = connected_peers(client_side)
    sender.update_settings({SettingCodes.HEADER_TABLE_SIZE: 1024})
    pending_frame = sender.data_to_send()
    with pytest.raises(InvalidSettingsValueError):
        sender.update_settings({SettingCodes.HEADER_TABLE_SIZE: 2048, SettingCodes.INITIAL_WINDOW_SIZE: -1})
    assert sender.data_to_send() == b""
    peer.receive_data(pending_frame)
    sender.receive_data(peer.data_to_send())
    assert sender.local_settings.header_table_size == peer.remote_settings.header_table_size == 1024

    sender.update_settings({})
    peer.receive_data(sender.data_to_send())
    acknowledgements = sender.receive_data(peer.data_to_send())
    assert len(acknowledgements) == 1
    assert isinstance(acknowledgements[0], SettingsAcknowledged)
    assert acknowledgements[0].changed_settings == {}
    assert sender.local_settings.header_table_size == peer.remote_settings.header_table_size == 1024


@pytest.mark.parametrize("client_side", [True, False])
def test_valid_queued_settings_keep_order_and_unknown_codes(client_side: bool) -> None:
    """Valid pending values retain their order and unknown setting codes."""
    sender, peer = connected_peers(client_side)
    unknown = 61
    frames = []
    for value in (1024, 2048):
        sender.update_settings({SettingCodes.HEADER_TABLE_SIZE: value, unknown: value})
        frames.append(sender.data_to_send())
    assert sender.local_settings.header_table_size == 4096
    with pytest.raises(KeyError):
        _ = sender.local_settings[unknown]
    for frame, value in zip(frames, (1024, 2048), strict=True):
        peer.receive_data(frame)
        acknowledgements = sender.receive_data(peer.data_to_send())
        assert len(acknowledgements) == 1
        assert isinstance(acknowledgements[0], SettingsAcknowledged)
        assert set(acknowledgements[0].changed_settings) == {SettingCodes.HEADER_TABLE_SIZE, unknown}
        assert sender.local_settings.header_table_size == peer.remote_settings.header_table_size == value
        assert sender.local_settings[unknown] == peer.remote_settings[unknown] == value


@pytest.mark.parametrize("client_side", [True, False])
def test_closed_connection_still_rejects_before_setting_validation(client_side: bool) -> None:
    """Connection-state errors retain precedence over invalid setting values."""
    sender, _ = connected_peers(client_side)
    sender.close_connection()
    with pytest.raises(ProtocolError) as exc:
        sender.update_settings({SettingCodes.INITIAL_WINDOW_SIZE: -1})
    assert not isinstance(exc.value, InvalidSettingsValueError)

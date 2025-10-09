"""unit tests for ordinary vs extended CONNECT validation on the client side."""

from __future__ import annotations

import pytest

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.utilities import HeaderValidationFlags, validate_outbound_headers


def _new_conn() -> H2Connection:
    c = H2Connection(
        config=H2Configuration(client_side=True, header_encoding="utf-8")
    )
    c.initiate_connection()
    # settings ack frame: length=0, type=4, flags=1(ACK), stream=0
    c.receive_data(b"\x00\x00\x00\x04\x01\x00\x00\x00\x00")
    return c


def _client_req_flags() -> HeaderValidationFlags:
    # client, not trailers, not response, not push
    return HeaderValidationFlags(
        is_client=True,
        is_trailer=False,
        is_response_header=False,
        is_push_promise=False,
    )


def test_ordinary_connect_allows_no_scheme_no_path_and_send_headers_ok() -> None:
    # ---- bytes for validate_outbound_headers ----
    hdrs_bytes = [
        (b":method", b"CONNECT"),
        (b":authority", b"example.com:443"),
    ]
    # should not raise
    list(validate_outbound_headers(hdrs_bytes, _client_req_flags()))

    # ---- str is fine for send_headers due to header_encoding ----
    hdrs_str = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
    ]
    conn = _new_conn()
    # should not raise
    conn.send_headers(1, hdrs_str, end_stream=True)


def test_ordinary_connect_rejects_path_or_scheme() -> None:
    bad1 = [
        (b":method", b"CONNECT"),
        (b":authority", b"example.com:443"),
        (b":path", b"/"),
    ]
    bad2 = [
        (b":method", b"CONNECT"),
        (b":authority", b"example.com:443"),
        (b":scheme", b"https"),
    ]
    with pytest.raises(Exception):
        list(validate_outbound_headers(bad1, _client_req_flags()))
    with pytest.raises(Exception):
        list(validate_outbound_headers(bad2, _client_req_flags()))


def test_extended_connect_requires_regular_tuple_and_send_headers_ok() -> None:
    hdrs_bytes = [
        (b":method", b"CONNECT"),
        (b":protocol", b"websocket"),
        (b":scheme", b"https"),
        (b":path", b"/chat?room=1"),
        (b":authority", b"ws.example.com"),
    ]
    # should not raise
    list(validate_outbound_headers(hdrs_bytes, _client_req_flags()))

    hdrs_str = [
        (":method", "CONNECT"),
        (":protocol", "websocket"),
        (":scheme", "https"),
        (":path", "/chat?room=1"),
        (":authority", "ws.example.com"),
    ]
    conn = _new_conn()
    # should not raise
    conn.send_headers(3, hdrs_str, end_stream=True)


def test_non_connect_still_requires_scheme_and_path() -> None:
    hdrs_bytes = [
        (b":method", b"GET"),
        (b":authority", b"example.com"),
        # omit :scheme and :path -> should raise
    ]
    with pytest.raises(Exception):
        list(validate_outbound_headers(hdrs_bytes, _client_req_flags()))


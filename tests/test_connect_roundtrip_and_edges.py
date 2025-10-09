"""round-trip and edge tests for ordinary vs extended CONNECT behavior."""

from __future__ import annotations


import pytest

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import RequestReceived
from h2.utilities import HeaderValidationFlags, validate_outbound_headers



def _new_conn(client_side: bool) -> H2Connection:
    return H2Connection(
        H2Configuration(client_side=client_side, header_encoding="utf-8")
    )


def _xfer_once(a: H2Connection, b: H2Connection):
    """
    move bytes from a -> b one step and return the events produced on b.
    """
    data = a.data_to_send()
    if not data:
        return []
    return b.receive_data(data)


def _shake(client: H2Connection, server: H2Connection) -> None:
    client.initiate_connection()
    server.initiate_connection()
    _xfer_once(client, server)
    _xfer_once(server, client)


def _drain_events(
    src: H2Connection, dst: H2Connection, max_iters: int = 10
) -> list:
    """
    keep transferring until src has nothing more to send (or max_iters reached).
    return the list of all events generated on dst.
    """
    out = []
    for _ in range(max_iters):
        evs = _xfer_once(src, dst)
        if not evs:
            break
        out.extend(evs)
    return out


def _validate_bytes(hdrs) -> None:
    flags = HeaderValidationFlags(
        is_client=True,
        is_trailer=False,
        is_response_header=False,
        is_push_promise=False,
    )
    # force bytes; validate_outbound_headers expects (bytes, bytes) tuples
    hdrs_b = [
        (
            k if isinstance(k, bytes) else k.encode("ascii"),
            v if isinstance(v, bytes) else v.encode("ascii"),
        )
        for (k, v) in hdrs
    ]
    # exhaust generator to trigger validation side-effects
    list(validate_outbound_headers(hdrs_b, flags))  # noqa: B018 (intentional)


def test_roundtrip_ordinary_connect_no_path_ok() -> None:
    client = _new_conn(True)
    server = _new_conn(False)
    _shake(client, server)

    # ordinary CONNECT: only :method and :authority
    hdrs = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
    ]
    _validate_bytes(hdrs)

    stream_id = 1
    client.send_headers(stream_id, hdrs, end_stream=True)
    evs = _drain_events(client, server)

    req_evs = [e for e in evs if isinstance(e, RequestReceived)]
    assert req_evs, "server should receive a RequestReceived"
    ps = {k: v for k, v in req_evs[0].headers if k.startswith(":")}
    assert ps[":method"] == "CONNECT"
    assert ps[":authority"] == "example.com:443"
    assert ":scheme" not in ps and ":path" not in ps


def test_roundtrip_extended_connect_websocket_ok() -> None:
    client = _new_conn(True)
    server = _new_conn(False)
    _shake(client, server)

    # extended CONNECT for WebSocket (RFC 8441 §4)
    hdrs = [
        (":method", "CONNECT"),
        (":protocol", "websocket"),
        (":scheme", "https"),
        (":path", "/chat?room=1"),
        (":authority", "ws.example.com"),
    ]
    _validate_bytes(hdrs)

    stream_id = 1
    client.send_headers(stream_id, hdrs, end_stream=True)
    evs = _drain_events(client, server)

    req_evs = [e for e in evs if isinstance(e, RequestReceived)]
    assert req_evs
    ps = {k: v for k, v in req_evs[0].headers if k.startswith(":")}
    assert ps[":method"] == "CONNECT"
    assert ps[":protocol"] == "websocket"
    assert ps[":scheme"] == "https"
    assert ps[":path"] == "/chat?room=1"
    assert ps[":authority"] == "ws.example.com"


def test_extended_connect_rejects_if_tuple_incomplete() -> None:
    # :protocol present but missing :scheme/:path => should fail validation
    hdrs = [
        (":method", "CONNECT"),
        (":protocol", "websocket"),
        (":authority", "ws.example.com"),
        # no :scheme, no :path
    ]
    with pytest.raises(Exception):
        _validate_bytes(hdrs)


def test_ordinary_connect_rejects_path_or_scheme() -> None:
    bad1 = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
        (":path", "/"),
    ]
    bad2 = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
        (":scheme", "https"),
    ]
    with pytest.raises(Exception):
        _validate_bytes(bad1)
    with pytest.raises(Exception):
        _validate_bytes(bad2)


def test_pseudo_headers_must_come_first() -> None:
    # a regular header before a pseudo-header should be rejected
    hdrs = [
        ("host", "example.com"),
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
    ]
    with pytest.raises(Exception):
        _validate_bytes(hdrs)


def test_duplicate_pseudo_header_rejected() -> None:
    hdrs = [
        (":method", "CONNECT"),
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
    ]
    with pytest.raises(Exception):
        _validate_bytes(hdrs)


def test_large_header_block_continuation_ok() -> None:
    client = _new_conn(True)
    server = _new_conn(False)
    _shake(client, server)

    # many regular headers to force CONTINUATION frames
    big = [(f"x-h{i}", "y" * 200) for i in range(200)]
    hdrs = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
    ] + big

    _validate_bytes(hdrs)
    client.send_headers(1, hdrs, end_stream=True)

    evs = _drain_events(client, server, max_iters=20)
    req_evs = [e for e in evs if isinstance(e, RequestReceived)]
    assert req_evs
    got = dict(req_evs[0].headers)
    assert "x-h0" in got and str(got["x-h0"]).startswith("y")


def test_te_header_rules() -> None:
    # only "te: trailers" is legal in HTTP/2 requests. anything else must be rejected.
    ok = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
        ("te", "trailers"),
    ]
    _validate_bytes(ok)  # should not raise

    bad = [
        (":method", "CONNECT"),
        (":authority", "example.com:443"),
        ("te", "gzip"),
    ]
    with pytest.raises(Exception):
        _validate_bytes(bad)


def test_multiple_concurrent_connect_streams_ok() -> None:
    client = _new_conn(True)
    server = _new_conn(False)
    _shake(client, server)

    s1 = 1
    s2 = 3
    hdrs = [
        (":method", "CONNECT"),
        (":authority", "example.internal:3128"),
    ]
    _validate_bytes(hdrs)
    client.send_headers(s1, hdrs, end_stream=True)
    client.send_headers(s2, hdrs, end_stream=True)

    evs = _drain_events(client, server, max_iters=10)
    reqs = [e for e in evs if isinstance(e, RequestReceived)]
    assert len(reqs) == 2


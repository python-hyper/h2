"""Exercise the documented client against a local TLS HTTP/2 server."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import shutil
import ssl
import subprocess

import pytest

import h2.config
import h2.connection
import h2.events


@pytest.fixture(scope="module")
def client():
    path = Path(__file__).parents[1] / "examples/asyncio/asyncio-client.py"
    spec = importlib.util.spec_from_file_location("asyncio_client_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required to generate a local test certificate")
    path = tmp_path_factory.mktemp("asyncio-client-tls")
    cert, key = path / "cert.pem", path / "key.pem"
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
    ], check=True, capture_output=True)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    server.set_alpn_protocols(["h2"])
    trusted = ssl.create_default_context(cafile=str(cert))
    return server, trusted


async def exercise(client, tls, mode, payload=b""):
    server_context, client_context = tls
    done = asyncio.get_running_loop().create_future()
    disconnected = asyncio.Event()
    requested = asyncio.Event()
    request = []

    async def respond(reader, writer):
        conn = h2.connection.H2Connection(config=h2.config.H2Configuration(
            client_side=False, header_encoding="utf-8",
        ))
        conn.initiate_connection()
        writer.write(conn.data_to_send())
        offset, stream_id = 0, None
        sent = False
        try:
            while data := await reader.read(65536):
                for event in conn.receive_data(data):
                    if isinstance(event, h2.events.RequestReceived):
                        assert not conn.remote_settings.enable_push
                        request.extend(event.headers)
                        requested.set()
                        stream_id = event.stream_id
                        if mode == "reset":
                            conn.reset_stream(stream_id)
                        elif mode == "goaway":
                            conn.close_connection()
                        elif mode == "eof":
                            return
                        elif mode != "wait":
                            conn.send_headers(stream_id, [(":status", "103"), ("link", "</style.css>")])
                            conn.send_headers(stream_id, [(":status", "200")], end_stream=mode == "empty")
                            sent = mode == "empty"
                    elif isinstance(event, h2.events.ConnectionTerminated):
                        return
                if stream_id and not sent and mode in {"body", "trailers", "complete-goaway"}:
                    while offset < len(payload) and conn.local_flow_control_window(stream_id) > 1:
                        # Count the pad-length byte too, to test flow_controlled_length.
                        size = min(len(payload) - offset, conn.local_flow_control_window(stream_id) - 1,
                                   conn.max_outbound_frame_size - 1)
                        conn.send_data(stream_id, payload[offset:offset + size], pad_length=0)
                        offset += size
                    if offset == len(payload):
                        if mode == "trailers":
                            conn.send_headers(stream_id, [("x-finished", "yes")], end_stream=True)
                        else:
                            conn.end_stream(stream_id)
                        if mode == "complete-goaway":
                            conn.close_connection()
                        sent = True
                writer.write(conn.data_to_send())
                await writer.drain()
        except Exception as exc:
            if not done.done():
                done.set_exception(exc)
        finally:
            writer.close()
            await writer.wait_closed()
            disconnected.set()
            if not done.done():
                done.set_result(None)

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    async with server:
        task = asyncio.create_task(client.get("localhost", port, "/resource?q=1", context=client_context))
        try:
            if mode == "wait":
                await asyncio.wait_for(requested.wait(), 5)
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(task, 0.2)
                result = None
            elif mode in {"reset", "goaway", "eof"}:
                with pytest.raises((RuntimeError, EOFError)):
                    await asyncio.wait_for(task, 5)
                result = None
            else:
                result = await asyncio.wait_for(task, 5)
            await asyncio.wait_for(disconnected.wait(), 5)
            await done
            assert (":authority", f"localhost:{port}") in request
            assert (":path", "/resource?q=1") in request
            return result
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("mode", ["body", "trailers", "empty", "complete-goaway"])
def test_response(client, tls, mode):
    payload = bytes(range(256)) * 1024 if mode != "empty" else b""
    headers, body, trailers = asyncio.run(exercise(client, tls, mode, payload))
    assert headers == [(":status", "200")]
    assert body == payload
    assert trailers == ([("x-finished", "yes")] if mode == "trailers" else [])


@pytest.mark.parametrize("mode", ["reset", "goaway", "eof", "wait"])
def test_failure_closes_transport(client, tls, mode):
    asyncio.run(exercise(client, tls, mode))


def test_alpn_failure_sends_no_h2_bytes(client, tls):
    async def check():
        server_context, trusted = tls
        server_context.set_alpn_protocols(["http/1.1"])
        received = asyncio.get_running_loop().create_future()

        async def respond(reader, writer):
            received.set_result(await reader.read())
            writer.close()
            await writer.wait_closed()

        try:
            server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=server_context)
            async with server:
                with pytest.raises(RuntimeError, match="negotiate HTTP/2"):
                    await client.get("localhost", server.sockets[0].getsockname()[1], context=trusted)
                assert await asyncio.wait_for(received, 5) == b""
        finally:
            server_context.set_alpn_protocols(["h2"])

    asyncio.run(check())

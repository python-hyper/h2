#!/usr/bin/env python3
"""A single-request HTTP/2 client using asyncio streams and verified TLS."""
from __future__ import annotations

import argparse
import asyncio
import ssl
import sys

import h2.config
import h2.connection
import h2.events
import h2.settings


async def get(host, port=443, path="/", *, context=None):
    """Return response headers, body bytes and trailers for one HTTPS GET."""
    if context is None:
        context = ssl.create_default_context()
    context.set_alpn_protocols(["h2"])
    reader, writer = await asyncio.open_connection(
        host, port, ssl=context, server_hostname=host,
    )
    try:
        if writer.get_extra_info("ssl_object").selected_alpn_protocol() != "h2":
            raise RuntimeError("The server did not negotiate HTTP/2")

        # One coroutine owns this connection and all calls into its h2 state.
        conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(header_encoding="utf-8"),
        )
        conn.initiate_connection()
        conn.update_settings({h2.settings.SettingCodes.ENABLE_PUSH: 0})
        stream_id = conn.get_next_available_stream_id()
        authority = f"[{host}]" if ":" in host else host
        if port != 443:
            authority += f":{port}"
        conn.send_headers(stream_id, [
            (":method", "GET"), (":scheme", "https"),
            (":authority", authority), (":path", path),
        ], end_stream=True)
        writer.write(conn.data_to_send())
        await writer.drain()

        headers, trailers = [], []
        body = bytearray()
        complete = False
        terminated = False
        while not complete:
            data = await reader.read(65536)
            if not data:
                raise EOFError("Connection closed before the response ended")
            events = conn.receive_data(data)
            # receive_data processes the whole batch before returning events.
            # A GOAWAY can accompany the completed response in that batch.
            terminated = any(isinstance(e, h2.events.ConnectionTerminated) for e in events)
            for event in events:
                if isinstance(event, h2.events.DataReceived):
                    if event.stream_id == stream_id:
                        body.extend(event.data)
                    if not terminated:
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id,
                        )
                elif getattr(event, "stream_id", None) != stream_id:
                    continue
                elif isinstance(event, h2.events.ResponseReceived):
                    headers = event.headers
                elif isinstance(event, h2.events.TrailersReceived):
                    trailers = event.headers
                elif isinstance(event, h2.events.StreamReset):
                    raise RuntimeError(f"Response stream reset: {event.error_code}")
                elif isinstance(event, h2.events.StreamEnded):
                    complete = True
            if terminated and not complete:
                raise RuntimeError("Server sent GOAWAY before the response ended")
            # Flush SETTINGS/PING acknowledgments and WINDOW_UPDATE frames.
            writer.write(conn.data_to_send())
            await writer.drain()

        if not terminated:
            conn.close_connection()
            writer.write(conn.data_to_send())
            await writer.drain()
        return headers, bytes(body), trailers
    finally:
        # Also release the transport on errors, cancellation and timeout.
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("path", nargs="?", default="/")
    parser.add_argument("--port", type=int, default=443)
    args = parser.parse_args()
    headers, body, trailers = asyncio.run(asyncio.wait_for(
        get(args.host, args.port, args.path), timeout=15,
    ))
    for name, value in headers + trailers:
        print(f"{name}: {value}", file=sys.stderr)
    sys.stdout.buffer.write(body)


if __name__ == "__main__":
    main()

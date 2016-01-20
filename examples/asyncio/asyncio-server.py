# -*- coding: utf-8 -*-
"""
asyncio-server.py
~~~~~~~~~~~~~~~~~

A fully-functional HTTP/2 server using asyncio. Requires Python 3.5+.
"""
import asyncio
import json
import ssl
import collections
from typing import List, Tuple

from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived


class H2Protocol(asyncio.Protocol):
    def __init__(self):
        self.conn = H2Connection(client_side=False)
        self.transport = None

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        self.conn.initiate_connection()
        self.transport.write(self.conn.data_to_send())

    def data_received(self, data: bytes):
        events = self.conn.receive_data(data)
        self.transport.write(self.conn.data_to_send())

        for event in events:
            if isinstance(event, RequestReceived):
                self.request_received(event.headers, event.stream_id)
            elif isinstance(event, DataReceived):
                self.conn.reset_stream(event.stream_id)

            self.transport.write(self.conn.data_to_send())

    def request_received(self, headers: List[Tuple[str, str]], stream_id: int):
        headers = collections.OrderedDict(headers)
        data = json.dumps({"headers": headers}, indent=4).encode("utf8")

        response_headers = (
            (':status', '200'),
            ('content-type', 'application/json'),
            ('content-length', len(data)),
            ('server', 'asyncio-h2'),
        )
        self.conn.send_headers(stream_id, response_headers)
        self.conn.send_data(stream_id, data, end_stream=True)


ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.options |= (
    ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_COMPRESSION
)
ssl_context.set_ciphers("ECDHE+AESGCM")
ssl_context.load_cert_chain(certfile="cert.crt", keyfile="cert.key")
ssl_context.set_alpn_protocols(["h2"])

loop = asyncio.get_event_loop()
# Each client connection will create a new protocol instance
coro = loop.create_server(H2Protocol, '127.0.0.1', 8443, ssl=ssl_context)
server = loop.run_until_complete(coro)

# Serve requests until Ctrl+C is pressed
print('Serving on {}'.format(server.sockets[0].getsockname()))
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

# Close the server
server.close()
loop.run_until_complete(server.wait_closed())
loop.close()

# -*- coding: utf-8 -*-
"""
curio-server.py
~~~~~~~~~~~~~~~

A fully-functional HTTP/2 server written for curio.

Requires Python 3.5+.
"""
import collections
import json

from curio import Kernel, new_task, socket, ssl

import h2.connection
import h2.events


def create_listening_ssl_socket(address):
    """
    Create and return a listening TLS socket on a given address.
    """
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile="cert.crt", keyfile="cert.key")
    ssl_context.set_alpn_protocols(["h2"])

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock = ssl_context.wrap_socket(sock)
    sock.bind(address)
    sock.listen()

    return sock


async def h2_server(address):
    """
    Create an HTTP/2 server at the given address.
    """
    sock = create_listening_ssl_socket(address)
    print("Now listening on %s:%d" % address)

    with sock:
        while True:
            client, _ = await sock.accept()
            server = H2Server(client)
            await new_task(server.run())


class H2Server:
    """
    A basic HTTP/2 echo server.
    """
    def __init__(self, sock):
        self.sock = sock
        self.conn = h2.connection.H2Connection(client_side=False)

    async def run(self):
        """
        Loop over the connection, managing it appropriately.
        """
        self.conn.initiate_connection()
        await self.sock.sendall(self.conn.data_to_send())

        while True:
            data = await self.sock.recv(65535)
            if not data:
                break

            events = self.conn.receive_data(data)
            for event in events:
                if isinstance(event, h2.events.RequestReceived):
                    self.request_received(event.headers, event.stream_id)
                elif isinstance(event, h2.events.DataReceived):
                    self.conn.reset_stream(event.stream_id)
                elif isinstance(event, h2.events.RemoteSettingsChanged):
                    self.conn.acknowledge_settings(event)

            await self.sock.sendall(self.conn.data_to_send())

    def request_received(self, headers, stream_id):
        """
        Handle a request by writing a simple response that echoes the headers
        from the request back in JSON.
        """
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


if __name__ == '__main__':
    kernel = Kernel()
    kernel.add_task(h2_server(('', 8080)))
    kernel.run()

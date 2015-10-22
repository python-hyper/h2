# -*- coding: utf-8 -*-
"""
gevent-server.py
~~~~~~~~~~~~~~~~

An HTTP/2 server written for gevent.
"""

import json
import time

import gevent
from gevent import socket

import h2.connection
import h2.events


class ConnectionManager(object):
    """
    An object that manages a single HTTP/2 connection.
    """
    def __init__(self, sock):
        self.sock = sock
        self.conn = h2.connection.H2Connection(client_side=False)

    def run_forever(self):
        self.conn.initiate_connection()
        self.sock.sendall(self.conn.data_to_send())

        while True:
            data = self.sock.recv(65535)
            if not data:
                break

            events = self.conn.receive_data(data)

            for event in events:
                if isinstance(event, h2.events.RequestReceived):
                    self.request_received(event)
                elif isinstance(event, h2.events.DataReceived):
                    self.conn.reset_stream(event.stream_id)
                elif isinstance(event, h2.events.RemoteSettingsChanged):
                    self.conn.acknowledge_settings(event)

            data_to_send = self.conn.data_to_send()
            if data_to_send:
                self.sock.sendall(data_to_send)

    def request_received(self, event):
        stream_id = event.stream_id
        response_data = json.dumps({'headers': dict(event.headers)}, indent=4).encode('utf-8')

        self.conn.send_headers(
            stream_id=stream_id,
            headers=(
                (':status', '200'),
                ('server', 'gevent-h2'),
                ('content-len', len(response_data)),
                ('content-type', 'application/json')
            )
        )

        self.conn.send_data(
            stream_id=stream_id,
            data=response_data,
            end_stream=True
        )


sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 8080))
sock.listen(5)

while True:
    manager = ConnectionManager(sock.accept()[0])
    gevent.spawn(manager.run_forever)

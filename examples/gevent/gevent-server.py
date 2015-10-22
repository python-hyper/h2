# -*- coding: utf-8 -*-
"""
gevent-server.py
~~~~~~~~~~~~~~~~

An HTTP/2 server written for gevent.
"""
import collections
import json

import gevent

from gevent import socket
from OpenSSL import SSL, crypto
from h2.connection import H2Connection
from h2.events import RequestReceived, DataReceived, RemoteSettingsChanged


class ConnectionManager(object):
    """
    An object that manages a single HTTP/2 connection.
    """
    def __init__(self, sock):
        self.sock = sock
        self.conn = H2Connection(client_side=False)

    def run_forever(self):
        self.conn.initiate_connection()
        self.sock.sendall(self.conn.data_to_send())

        while True:
            data = self.sock.recv(65535)
            if not data:
                break

            events = self.conn.receive_data(data)

            for event in events:
                if isinstance(event, RequestReceived):
                    self.request_received(event.headers, event.stream_id)
                elif isinstance(event, DataReceived):
                    self.conn.reset_stream(event.stream_id)
                elif isinstance(event, RemoteSettingsChanged):
                    self.conn.acknowledge_settings(event)

            self.sock.sendall(self.conn.data_to_send())

    def request_received(self, event):
        headers = dict(event.headers)
        data = json.dumps({'headers': headers}, indent=4).encode('utf-8')

        response_headers = (
            (':status', '200'),
            ('content-type', 'application/json'),
            ('content-length', len(data)),
            ('server', 'gevent-h2'),
        )
        self.conn.send_headers(event.stream_id, response_headers)
        self.conn.send_data(event.stream_id, data, end_stream=True)


def alpn_callback(conn, protos):
    if b'h2' in protos:
        return b'h2'

    raise RuntimeError("No acceptable protocol offered!")


def npn_advertise_cb(conn):
    return [b'h2']


# Let's set up SSL. This is a lot of work in PyOpenSSL.
context = SSL.Context(SSL.SSLv23_METHOD)
context.set_verify(SSL.VERIFY_NONE, lambda *args: True)
context.use_privatekey_file('server.key')
context.use_certificate_file('server.crt')
context.set_npn_advertise_callback(npn_advertise_cb)
context.set_alpn_select_callback(alpn_callback)
context.set_cipher_list(
    "ECDHE+AESGCM"
)
context.set_tmp_ecdh(crypto.get_elliptic_curve(u'prime256v1'))

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 443))
sock.listen(5)

server = SSL.Connection(context, sock)

while True:
    try:
        new_sock, _ = server.accept()
        manager = ConnectionManager(new_sock)
        gevent.spawn(manager.run_forever)
    except (SystemExit, KeyboardInterrupt):
        break
# -*- coding: utf-8 -*-
"""
twisted-server.py
~~~~~~~~~~~~~~~~~

A fully-functional HTTP/2 server written for Twisted.
"""
import mimetypes
import os
import os.path
import sys

from OpenSSL import crypto
from twisted.internet.protocol import Protocol, Factory
from twisted.internet import reactor, ssl
from h2.connection import H2Connection
from h2.events import RequestReceived, DataReceived, RemoteSettingsChanged


READ_CHUNK_SIZE = 8192


class H2Protocol(Protocol):
    def __init__(self, root):
        self.conn = H2Connection(client_side=False)
        self.known_proto = None
        self.root = root

    def connectionMade(self):
        self.conn.initiate_connection()
        self.transport.write(self.conn.data_to_send())

    def dataReceived(self, data):
        if not self.known_proto:
            print self.transport.getNextProtocol()
            self.known_proto = True

        events = self.conn.receive_data(data)
        if self.conn.data_to_send:
            self.transport.write(self.conn.data_to_send())

        for event in events:
            if isinstance(event, RequestReceived):
                self.requestReceived(event.headers, event.stream_id)
            elif isinstance(event, DataReceived):
                self.dataFrameReceived(event.stream_id)
            elif isinstance(event, RemoteSettingsChanged):
                self.settingsChanged(event)

    def requestReceived(self, headers, stream_id):
        headers = dict(headers)  # Invalid conversion, fix later.
        assert headers[':method'] == 'GET'

        path = headers[':path'].lstrip('/')
        full_path = os.path.join(self.root, path)

        if not os.path.exists(full_path):
            response_headers = (
                (':status', '404'),
                ('content-length', '0'),
                ('server', 'twisted-h2'),
            )
            self.conn.send_headers(
                stream_id, response_headers, end_stream=True
            )
            self.transport.write(self.conn.data_to_send())
        else:
            self.sendFile(full_path, stream_id)

        return

    def dataFrameReceived(self, stream_id):
        self.conn.reset_stream(stream_id)
        self.transport.write(self.conn.data_to_send())

    def settingsChanged(self, event):
        print event.changed_settings
        self.conn.acknowledge_settings(event)
        self.transport.write(self.conn.data_to_send())

    def sendFile(self, file_path, stream_id):
        filesize = os.stat(file_path).st_size
        content_type, content_encoding = mimetypes.guess_type(file_path)
        response_headers = [
            (':status', '200'),
            ('content-length', str(filesize)),
            ('server', 'twisted-h2'),
        ]
        if content_type:
            response_headers.append(('content-type', content_type))
        if content_encoding:
            response_headers.append(('content-encoding', content_encoding))

        self.conn.send_headers(stream_id, response_headers)
        self.transport.write(self.conn.data_to_send())

        with open(file_path, 'rb') as f:
            to_read = True

            while to_read:
                data = f.read(READ_CHUNK_SIZE)
                to_read = len(data) == READ_CHUNK_SIZE
                self.conn.send_data(stream_id, data, not to_read)
                self.transport.write(self.conn.data_to_send())

        return


class H2Factory(Factory):
    def __init__(self, root):
        self.root = root

    def buildProtocol(self, addr):
        return H2Protocol(self.root)

root = sys.argv[1]

with open('server.crt', 'r') as f:
    cert_data = f.read()
with open('server.key', 'r') as f:
    key_data = f.read()

cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_data)
key = crypto.load_privatekey(crypto.FILETYPE_PEM, key_data)
options = ssl.CertificateOptions(
    privateKey=key,
    certificate=cert,
    nextProtocols=[b'h2', b'http/1.1'],
)

reactor.listenSSL(8080, H2Factory(root), options)
reactor.run()

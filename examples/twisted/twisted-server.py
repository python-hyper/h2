# -*- coding: utf-8 -*-
"""
twisted-server.py
~~~~~~~~~~~~~~~~~

A fully-functional HTTP/2 server written for Twisted.
"""
import json

from OpenSSL import crypto
from twisted.internet.protocol import Protocol, Factory
from twisted.internet import reactor, ssl
from h2.connection import H2Connection
from h2.events import RequestReceived, DataReceived, RemoteSettingsChanged


class H2Protocol(Protocol):
    def __init__(self):
        self.conn = H2Connection(client_side=False)
        self.known_proto = None

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
        if headers[':path'] == '/':

            data = json.dumps({'headers': headers}).encode("utf8")

            response_headers = (
                (':status', '200'),
                ('content-type', 'application/json'),
                ('content-length', len(data)),
                ('server', 'twisted-h2'),
            )
            self.conn.send_headers(stream_id, response_headers)
            self.conn.send_data(stream_id, data, end_stream=True)

            self.transport.write(self.conn.data_to_send())
        else:
            response_headers = (
                (':status', '404'),
                ('server', 'twisted-h2'),
                ('content-length', '0'),
            )
            self.conn.send_headers(
                stream_id, response_headers, end_stream=True
            )
            self.transport.write(self.conn.data_to_send())

    def dataFrameReceived(self, stream_id):
        self.conn.reset_stream(stream_id)
        self.transport.write(self.conn.data_to_send())

    def settingsChanged(self, event):
        print event.changed_settings
        self.conn.acknowledge_settings(event)
        self.transport.write(self.conn.data_to_send())


class H2Factory(Factory):
    def buildProtocol(self, addr):
        return H2Protocol()


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

reactor.listenSSL(8080, H2Factory(), options)
reactor.run()

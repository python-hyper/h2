# -*- coding: utf-8 -*-
"""
twisted-server.py
~~~~~~~~~~~~~~~~~

A fully-functional HTTP/2 server written for Twisted.
"""
import json

from twisted.internet.protocol import Protocol, Factory
from twisted.internet import reactor
from h2.connection import H2Connection
from h2.events import RequestReceived, DataReceived, RemoteSettingsChanged


class H2Protocol(Protocol):
    def __init__(self):
        self.conn = H2Connection(client_side=False)

    def connectionMade(self):
        self.conn.initiate_connection()
        self.transport.write(self.conn.data_to_send)
        self.conn.data_to_send = b''

    def dataReceived(self, data):
        events = self.conn.receive_data(data)
        if self.conn.data_to_send:
            self.transport.write(self.conn.data_to_send)
            self.conn.data_to_send = b''

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
        assert headers[':path'] == '/'

        data = json.dumps({'headers': headers})

        response_headers = (
            (':status', '200'),
            ('content-type', 'application/json'),
            ('content-length', len(data)),
            ('server', 'twisted-h2'),
        )
        self.conn.send_headers(stream_id, response_headers)
        self.conn.send_data(stream_id, data, end_stream=True)

        self.transport.write(self.conn.data_to_send)
        self.conn.data_to_send = b''

    def dataFrameReceived(self, stream_id):
        self.conn.reset_stream(stream_id)
        self.transport.write(self.conn.data_to_send)
        self.conn.data_to_send = b''

    def settingsChanged(self, event):
        self.conn.acknowledge_settings(event)
        self.transport.write(self.conn.data_to_send)
        self.conn.data_to_send = b''


class H2Factory(Factory):
    def buildProtocol(self, addr):
        return H2Protocol()

reactor.listenTCP(8080, H2Factory())
reactor.run()

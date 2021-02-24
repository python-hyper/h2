#!/usr/bin/env python3
import sys
import ssl
import json
import collections

import trio
import h2.config
import h2.connection
import h2.events

ReceivedData = collections.namedtuple("ReceivedData", ("headers", "data"))


class H2EchoServer:
    def __init__(self):
        config = h2.config.H2Configuration(client_side=False, header_encoding="utf-8")
        self.connection = h2.connection.H2Connection(config=config)
        self.received_data = {}
        self.flow_control_events = {}
        self.write_lock = trio.Lock()
        self.stream = None

    async def write_all_pending_data(self):
        async with self.write_lock:
            await self.stream.send_all(self.connection.data_to_send())

    def request_received(self, event):
        self.received_data[event.stream_id] = ReceivedData(event.headers, bytearray())

    def data_received(self, event):
        try:
            self.received_data[event.stream_id].data.extend(event.data)
        except KeyError:
            self.connection.reset_stream(event.stream_id,
                                         h2.errors.ErrorCodes.PROTOCOL_ERROR)
        else:
            self.connection.acknowledge_received_data(event.flow_controlled_length,
                                                      event.stream_id)

    async def reply_echo(self, stream_id):
        self.flow_control_events[stream_id] = trio.Event()
        response_body = json.dumps({
            "headers": collections.OrderedDict(self.received_data[stream_id].headers),
            "body": self.received_data[stream_id].data.decode("utf-8")
        }, indent=4).encode("utf-8")

        response_headers = (
            (":status", "200"),
            ("content-type", "application/json"),
            ("content-length", str(len(response_body))),
            ("server", "python-trio-h2"),
        )
        self.connection.send_headers(stream_id, response_headers)

        ptr = 0
        while ptr < len(response_body):
            while self.connection.local_flow_control_window(stream_id) == 0:
                await self.flow_control_events[stream_id]
            chunk_size = min(self.connection.max_outbound_frame_size,
                             self.connection.local_flow_control_window(stream_id))
            self.connection.send_data(stream_id, response_body[ptr:ptr+chunk_size])
            await self.write_all_pending_data()
            ptr += chunk_size
        self.connection.end_stream(stream_id)
        await self.write_all_pending_data()

    def window_updated(self, event):
        if event.stream_id == 0:
            for event in self.flow_control_events.values():
                event.set()
        else:
            try:
                self.flow_control_events[event.stream_id].set()
            except KeyError:
                self.connection.reset_stream(event.stream_id,
                                             h2.errors.ErrorCodes.PROTOCOL_ERROR)

    async def __call__(self, server_stream):
        self.stream = server_stream
        try:
            self.connection.initiate_connection()
            await self.write_all_pending_data()

            try:
                async with trio.open_nursery() as nursery:
                    while True:
                        data = await server_stream.receive_some(65536)
                        if not data:
                            return
                        events = self.connection.receive_data(data)
                        for event in events:
                            if isinstance(event, h2.events.RequestReceived):
                                self.request_received(event)
                            elif isinstance(event, h2.events.DataReceived):
                                self.data_received(event)
                            elif isinstance(event, h2.events.StreamEnded):
                                nursery.start_soon(self.reply_echo, event.stream_id)
                            elif isinstance(event, h2.events.WindowUpdated):
                                self.window_updated(event)
                            elif isinstance(event, h2.events.ConnectionTerminated):
                                return
                            await self.write_all_pending_data()
            finally:
                await self.write_all_pending_data()
        except:
            print("Got exception: {!r}".format(sys.exc_info()))


async def main(port):
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.options |= (
            ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_COMPRESSION
    )
    ssl_context.set_ciphers("ECDHE+AESGCM")
    ssl_context.load_cert_chain(certfile="cert.crt", keyfile="cert.key")
    ssl_context.set_alpn_protocols(["h2"])

    await trio.serve_ssl_over_tcp(lambda stream: H2EchoServer()(stream),
                                  port, ssl_context)


if __name__ == "__main__":
    port = int(sys.argv[1])
    print("Try: $ curl --tlsv1.2 --http2 -k https://localhost:{}/path -d'data'"
          .format(port))
    print("Or open a browser to https://localhost:{}/ and accept all the warnings"
          .format(port))
    trio.run(main, port)

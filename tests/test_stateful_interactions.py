"""Generate sequences of exchanges between two in-memory HTTP/2 peers."""

from __future__ import annotations

from dataclasses import dataclass, field

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, PingAckReceived, RequestReceived, ResponseReceived, StreamEnded, StreamReset, TrailersReceived
from h2.settings import SettingCodes


@dataclass
class Exchange:
    request: bytearray = field(default_factory=bytearray)
    response: bytearray = field(default_factory=bytearray)
    received_request: bytearray = field(default_factory=bytearray)
    received_response: bytearray = field(default_factory=bytearray)
    observed_request: bool = False
    observed_response: bool = False
    observed_reset: bool = False
    request_ended: bool = False
    response_started: bool = False
    response_ended: bool = False
    reset: bool = False
    observed_request_end: bool = False
    observed_response_end: bool = False


class InteractingPeers(RuleBasedStateMachine):
    """Keep a small application model independent of either peer's state machine."""

    def __init__(self) -> None:
        super().__init__()
        self.client = H2Connection(config=H2Configuration(client_side=True))
        self.server = H2Connection(config=H2Configuration(client_side=False))
        self.exchanges: dict[int, Exchange] = {}
        self.next_stream_id = 1
        self.ping_acks: list[bytes] = []
        self.client.initiate_connection()
        self.server.initiate_connection()
        self.deliver(self.client, self.server, 17)
        self.deliver(self.server, self.client, 17)
        self.deliver(self.client, self.server, 17)

    def deliver(self, sender: H2Connection, receiver: H2Connection, chunk: int) -> None:
        """Deliver fragmented wire bytes, including automatic ACKs, without I/O."""
        pending = [(sender, receiver)]
        rounds = 0
        while pending:
            rounds += 1
            assert rounds < 100, "automatic peer responses did not settle"
            source, destination = pending.pop()
            wire = source.data_to_send()
            if not wire:
                continue
            for offset in range(0, len(wire), chunk):
                for event in destination.receive_data(wire[offset : offset + chunk]):
                    self.observe(destination, event)
            pending.append((destination, source))

    def observe(self, receiver: H2Connection, event) -> None:
        if isinstance(event, PingAckReceived):
            self.ping_acks.append(event.ping_data)
        elif isinstance(event, RequestReceived):
            assert receiver is self.server
            exchange = self.exchanges[event.stream_id]
            assert not exchange.observed_request
            exchange.observed_request = True
            assert (b":method", b"POST") in event.headers
        elif isinstance(event, ResponseReceived):
            assert receiver is self.client
            exchange = self.exchanges[event.stream_id]
            assert exchange.response_started
            assert not exchange.observed_response
            exchange.observed_response = True
            assert (b":status", b"200") in event.headers
        elif isinstance(event, DataReceived):
            exchange = self.exchanges[event.stream_id]
            received = exchange.received_request if receiver is self.server else exchange.received_response
            received.extend(event.data)
            receiver.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
        elif isinstance(event, StreamEnded):
            exchange = self.exchanges[event.stream_id]
            if receiver is self.server:
                assert exchange.request_ended
                assert not exchange.observed_request_end
                exchange.observed_request_end = True
            else:
                assert exchange.response_ended
                assert not exchange.observed_response_end
                exchange.observed_response_end = True
        elif isinstance(event, StreamReset):
            exchange = self.exchanges[event.stream_id]
            assert exchange.reset
            assert not exchange.observed_reset
            exchange.observed_reset = True
        elif isinstance(event, TrailersReceived):
            assert event.headers == [(b"checksum", b"done")]

    @precondition(lambda self: len(self.exchanges) < 8)
    @rule(end_stream=st.booleans(), chunk=st.integers(1, 257))
    def request(self, end_stream: bool, chunk: int) -> None:
        stream_id = self.next_stream_id
        self.next_stream_id += 2
        self.exchanges[stream_id] = Exchange(request_ended=end_stream)
        self.client.send_headers(
            stream_id,
            [
                (":method", "POST"),
                (":scheme", "https"),
                (":authority", "example.com"),
                (":path", f"/{stream_id}"),
            ],
            end_stream=end_stream,
        )
        self.deliver(self.client, self.server, chunk)

    def request_streams(self) -> list[int]:
        return [sid for sid, exchange in self.exchanges.items() if not exchange.request_ended and not exchange.reset]

    def response_streams(self) -> list[int]:
        return [sid for sid, exchange in self.exchanges.items() if exchange.response_started and not exchange.response_ended and not exchange.reset]

    @precondition(lambda self: bool(self.request_streams()))
    @rule(data=st.data(), payload=st.binary(max_size=2048), end_stream=st.booleans(), chunk=st.integers(1, 257))
    def request_data(self, data, payload: bytes, end_stream: bool, chunk: int) -> None:
        stream_id = data.draw(st.sampled_from(self.request_streams()))
        exchange = self.exchanges[stream_id]
        payload = payload[: max(0, self.client.local_flow_control_window(stream_id))]
        exchange.request.extend(payload)
        exchange.request_ended = end_stream
        self.client.send_data(stream_id, payload, end_stream=end_stream)
        self.deliver(self.client, self.server, chunk)

    @precondition(lambda self: any(not e.response_started and not e.reset for e in self.exchanges.values()))
    @rule(data=st.data(), end_stream=st.booleans(), chunk=st.integers(1, 257))
    def response(self, data, end_stream: bool, chunk: int) -> None:
        available = [sid for sid, e in self.exchanges.items() if not e.response_started and not e.reset]
        stream_id = data.draw(st.sampled_from(available))
        exchange = self.exchanges[stream_id]
        exchange.response_started = True
        exchange.response_ended = end_stream
        self.server.send_headers(stream_id, [(":status", "200")], end_stream=end_stream)
        self.deliver(self.server, self.client, chunk)

    @precondition(lambda self: bool(self.response_streams()))
    @rule(data=st.data(), payload=st.binary(max_size=2048), end_stream=st.booleans(), chunk=st.integers(1, 257))
    def response_data(self, data, payload: bytes, end_stream: bool, chunk: int) -> None:
        stream_id = data.draw(st.sampled_from(self.response_streams()))
        exchange = self.exchanges[stream_id]
        payload = payload[: max(0, self.server.local_flow_control_window(stream_id))]
        exchange.response.extend(payload)
        exchange.response_ended = end_stream
        self.server.send_data(stream_id, payload, end_stream=end_stream)
        self.deliver(self.server, self.client, chunk)

    @precondition(lambda self: bool(self.request_streams() or self.response_streams()))
    @rule(data=st.data(), response_side=st.booleans(), chunk=st.integers(1, 257))
    def trailers(self, data, response_side: bool, chunk: int) -> None:
        available = self.response_streams() if response_side else self.request_streams()
        if not available:
            return
        stream_id = data.draw(st.sampled_from(available))
        exchange = self.exchanges[stream_id]
        if response_side:
            exchange.response_ended = True
            sender, receiver = self.server, self.client
        else:
            exchange.request_ended = True
            sender, receiver = self.client, self.server
        sender.send_headers(stream_id, [("checksum", "done")], end_stream=True)
        self.deliver(sender, receiver, chunk)

    @precondition(lambda self: any(not e.reset and not (e.request_ended and e.response_ended) for e in self.exchanges.values()))
    @rule(data=st.data(), client_side=st.booleans(), chunk=st.integers(1, 257))
    def reset(self, data, client_side: bool, chunk: int) -> None:
        available = [sid for sid, e in self.exchanges.items() if not e.reset and not (e.request_ended and e.response_ended)]
        stream_id = data.draw(st.sampled_from(available))
        self.exchanges[stream_id].reset = True
        sender, receiver = (self.client, self.server) if client_side else (self.server, self.client)
        sender.reset_stream(stream_id)
        self.deliver(sender, receiver, chunk)

    @rule(client_side=st.booleans(), window=st.integers(16384, 65535), chunk=st.integers(1, 257))
    def change_window(self, client_side: bool, window: int, chunk: int) -> None:
        sender, receiver = (self.client, self.server) if client_side else (self.server, self.client)
        sender.update_settings({SettingCodes.INITIAL_WINDOW_SIZE: window})
        self.deliver(sender, receiver, chunk)
        assert sender.local_settings.initial_window_size == window
        assert receiver.remote_settings.initial_window_size == window

    @rule(client_side=st.booleans(), opaque=st.binary(min_size=8, max_size=8), chunk=st.integers(1, 257))
    def ping(self, client_side: bool, opaque: bytes, chunk: int) -> None:
        sender, receiver = (self.client, self.server) if client_side else (self.server, self.client)
        count = len(self.ping_acks)
        sender.ping(opaque)
        self.deliver(sender, receiver, chunk)
        assert self.ping_acks[count:] == [opaque]

    @invariant()
    def application_data_agrees(self) -> None:
        for exchange in self.exchanges.values():
            assert exchange.observed_request
            assert exchange.response_started == exchange.observed_response
            assert exchange.reset == exchange.observed_reset
            assert exchange.request == exchange.received_request
            assert exchange.response == exchange.received_response
            assert exchange.request_ended == exchange.observed_request_end
            assert exchange.response_ended == exchange.observed_response_end


TestInteractingPeers = InteractingPeers.TestCase
TestInteractingPeers.settings = settings(max_examples=100, stateful_step_count=50, deadline=None)

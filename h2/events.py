# -*- coding: utf-8 -*-
"""
h2/events
~~~~~~~~~

Defines Event types for HTTP/2.

Events are returned by the H2 state machine to allow implementations to keep
track of events triggered by receiving data. Each time data is provided to the
H2 state machine it processes the data and returns a list of Event objects.
"""


class RequestReceived(object):
    """
    The RequestReceived event is fired whenever request headers are received.
    This event carries the HTTP headers for the given request and the stream ID
    of the new stream.
    """
    def __init__(self):
        self.stream_id = None
        self.headers = None


class ResponseReceived(object):
    """
    The ResponseReceived event is fired whenever request headers are received.
    This event carries the HTTP headers for the given response and the stream
    ID of the new stream.
    """
    def __init__(self):
        self.stream_id = None
        self.headers = None


class DataReceived(object):
    """
    The DataReceived event is fired whenever data is received on a stream from
    the remote peer. The event carries the data itself, and the stream ID on
    which the data was received.
    """
    def __init__(self):
        self.stream_id = None
        self.data = None

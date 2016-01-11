Release History
===============

dev
---

API Changes (Breaking)
~~~~~~~~~~~~~~~~~~~~~~

- Attempts to open streams with invalid stream IDs, either by the remote peer
  or by the user, are now rejected as a ``ProtocolError``.
- Receiving frames that have invalid padding now causes the connection to be
  terminated with a ``ProtocolError`` being raised.
- Settings values set by both the user and the remote peer are now validated
  when they're set. If they're invalid, a new ``InvalidSettingsValueError`` is
  raised and, if set by the remote peer, a connection error is signaled.

API Changes (Backward-Compatible)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added ``get_next_available_stream_id`` function.
- Receiving DATA frames on streams not in the OPEN or HALF_CLOSED_LOCAL states
  now causes a stream reset, rather than a connection reset. The error is now
  also classified as a ``StreamClosedError``, rather than a more generic
  ``ProtocolError``.
- Receiving HEADERS or PUSH_PROMISE frames in the HALF_CLOSED_REMOTE state now
  causes a stream reset, rather than a connection reset.
- Receiving frames that violate the max frame size now causes connection errors
  with error code FRAME_SIZE_ERROR, not a generic PROTOCOL_ERROR. This
  condition now also raises a ``FrameTooLargeError``, a new subclass of
  ``ProtocolError``.

Bugfixes
~~~~~~~~

- RFC 7540 requires that a separate minimum stream ID be used for inbound and
  outbound streams. Hyper-h2 now obeys this requirement.
- Hyper-h2 now does a better job of reporting the last stream ID it has
  partially handled when terminating connections.
- Fixed an error in the arguments of ``StreamIDTooLowError``.

1.1.1 (2015-11-17)
------------------

Bugfixes
~~~~~~~~

- Forcibly lowercase all header names to improve compatibility with
  implementations that demand lower-case header names.

1.1.0 (2015-10-28)
------------------

API Changes (Backward-Compatible)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added a new ``ConnectionTerminated`` event, which fires when GOAWAY frames
  are received.
- Added a subclass of ``NoSuchStreamError``, called ``StreamClosedError``, that
  fires when actions are taken on a stream that is closed and has had its state
  flushed from the system.
- Added ``StreamIDTooLowError``, raised when the user or the remote peer
  attempts to create a stream with an ID lower than one previously used in the
  dialog. Inherits from ``ValueError`` for backward-compatibility reasons.

Bugfixes
~~~~~~~~

- Do not throw ``ProtocolError`` when attempting to send multiple GOAWAY
  frames on one connection.
- We no longer forcefully change the decoder table size when settings changes
  are ACKed, instead waiting for remote acknowledgement of the change.
- Improve the performance of checking whether a stream is open.
- We now attempt to lazily garbage collect closed streams, to avoid having the
  state hang around indefinitely, leaking memory.
- Avoid further per-stream allocations, leading to substantial performance
  improvements when many short-lived streams are used.

1.0.0 (2015-10-15)
------------------

- First production release!

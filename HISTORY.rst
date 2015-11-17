Release History
===============

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

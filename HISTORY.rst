Release History
===============

dev
---

API Changes (Backward-Compatible)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added a new ``ConnectionTerminated`` event, which fires when GOAWAY frames
  are received.

Bugfixes
~~~~~~~~

- Do not throw ``ProtocolError``s when attempting to send multiple GOAWAY
  frames on one connection.
- We no longer forcefully change the decoder table size when settings changes
  are ACKed, instead waiting for remote acknowledgement of the change.

1.0.0 (2015-10-15)
------------------

- First production release!

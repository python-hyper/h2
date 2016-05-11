Advanced Usage
==============

Priority
--------

.. versionadded:: 2.0.0

`RFC 7540`_ has a fairly substantial and complex section describing how to
build a HTTP/2 priority tree, and the effect that should have on sending data
from a server.

Hyper-h2 does not enforce any priority logic by default for servers. This is
because scheduling data sends is outside the scope of this library, as it
likely requires fairly substantial understanding of the scheduler being used.

However, for servers that *do* want to follow the priority recommendations
given by clients, the Hyper project provides `an implementation`_ of the
`RFC 7540`_ priority tree that will be useful to plug into a server. That,
combined with the :class:`PriorityUpdated <h2.events.PriorityUpdated>` event from
this library, can be used to build a server that conforms to RFC 7540's
recommendations for priority handling.

.. _h2-connection-advanced:

Connections: Advanced
---------------------

Thread Safety
~~~~~~~~~~~~~

``H2Connection`` objects are *not* thread-safe. They cannot safely be accessed
from multiple threads at once. This is a deliberate design decision: it is not
trivially possible to design the ``H2Connection`` object in a way that would
be either lock-free or have the locks at a fine granularity.

Your implementations should bear this in mind, and handle it appropriately. It
should be simple enough to use locking alongside the ``H2Connection``: simply
lock around the connection object itself. Because the ``H2Connection`` object
does no I/O it should be entirely safe to do that. Alternatively, have a single
thread take ownership of the ``H2Connection`` and use a message-passing
interface to serialize access to the ``H2Connection``.

If you are using a non-threaded concurrency approach (e.g. Twisted), this
should not affect you.

Internal Buffers
~~~~~~~~~~~~~~~~

In order to avoid doing I/O, the ``H2Connection`` employs an internal buffer.
This buffer is *unbounded* in size: it can potentially grow infinitely. This
means that, if you are not making sure to regularly empty it, you are at risk
of exceeding the memory limit of a single process and finding your program
crashes.

It is highly recommended that you send data at regular intervals, ideally as
soon as possible.

.. _advanced-sending-data:

Sending Data
~~~~~~~~~~~~

When sending data on the network, it's important to remember that you may not
be able to send an unbounded amount of data at once. Particularly when using
TCP, it is often the case that there are limits on how much data may be in
flight at any one time. These limits can be very low, and your operating system
will only buffer so much data in memory before it starts to complain.

For this reason, it is possible to consume only a subset of the data available
when you call :meth:`data_to_send <h2.connection.H2Connection.data_to_send>`.
However, once you have pulled the data out of the ``H2Connection`` internal
buffer, it is *not* possible to put it back on again. For that reason, it is
adviseable that you confirm how much space is available in the OS buffer before
sending.

Alternatively, use tools made available by your framework. For example, the
Python standard library :mod:`socket <python:socket>` module provides a
:meth:`sendall <python:socket.socket.sendall>` method that will automatically
block until all the data has been sent. This will enable you to always use the
unbounded form of
:meth:`data_to_send <h2.connection.H2Connection.data_to_send>`, and will help
you avoid subtle bugs.

When To Send
~~~~~~~~~~~~

In addition to knowing how much data to send (see :ref:`advanced-sending-data`)
it is important to know when to send data. For hyper-h2, this amounts to
knowing when to call :meth:`data_to_send
<h2.connection.H2Connection.data_to_send>`.

Hyper-h2 may write data into its send buffer at two times. The first is
whenever :meth:`receive_data <h2.connection.H2Connection.receive_data>` is
called. This data is sent in response to some control frames that require no
user input: for example, responding to PING frames. The second time is in
response to user action: whenever a user calls a method like
:meth:`send_headers <h2.connection.H2Connection.send_headers>`, data may be
written into the buffer.

In a standard design for a hyper-h2 consumer, then, that means there are two
places where you'll potentially want to send data. The first is in your
"receive data" loop. This is where you take the data you receive, pass it into
:meth:`receive_data <h2.connection.H2Connection.receive_data>`, and then
dispatch events. For this loop, it is usually best to save sending data until
the loop is complete: that allows you to empty the buffer only once.

The other place you'll want to send the data is when initiating requests or
taking any other active, unprompted action on the connection. In this instance,
you'll want to make all the relevant ``send_*`` calls, and *then* call
:meth:`data_to_send <h2.connection.H2Connection.data_to_send>`.

Headers
-------

HTTP/2 defines several "special header fields" which are used to encode data
that was previously sent in either the request or status line of HTTP/1.1.
These header fields are distinguished from ordinary header fields because their
field name begins with a ``:`` character. The special header fields defined in
`RFC 7540`_ are:

- ``:status``
- ``:path``
- ``:method``
- ``:scheme``
- ``:authority``

`RFC 7540`_ **mandates** that all of these header fields appear *first* in the
header block, before the ordinary header fields. This can cause difficulty if
you call the :meth:`send_headers <h2.connection.H2Connection.send_headers>`
method with a plain ``dict`` for the ``headers`` argument, because ``dict``
objects are unordered.

For this reason, passing a ``dict`` to ``send_headers`` is *deprecated* as of
the 2.1 series of releases. This functionality will be removed entirely in
version 3.0 of hyper-h2.


.. _RFC 7540: https://tools.ietf.org/html/rfc7540
.. _an implementation: http://python-hyper/priority/

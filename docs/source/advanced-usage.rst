Advanced Usage
==============

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

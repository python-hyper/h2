Trio Example Server
====================

This example is a basic HTTP/2 echo server with TLS written using
`trio`_,  new ``async``/``await``-native I/O library for Python.

This example is notable for demonstrating the correct use of HTTP/2 flow
control with Hyper-h2. It is also a good example of using `trio`_ library,
including `trio.Lock`, `trio.Event`, `trio.open_nursery`, etc.

.. literalinclude:: ../../examples/trio/trio-server.py
   :language: python
   :linenos:
   :encoding: utf-8


.. _trio: https://trio.readthedocs.io/en/latest/

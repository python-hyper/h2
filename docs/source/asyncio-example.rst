Asyncio Example Server
======================

This example is a basic HTTP/2 server written using `asyncio`_, using some
functionality that was introduced in Python 3.5. This server represents
basically just the same JSON-headers-returning server that was built in the
:doc:`basic-usage` document.

This example demonstrates some basic asyncio techniques.

.. literalinclude:: ../../examples/asyncio/asyncio-server.py
   :language: python
   :linenos:
   :encoding: utf-8


You can use ``cert.crt`` and ``cert.key`` files provided within the repository
or generate your own certificates using `OpenSSL`_:

.. code-block:: console

   $ openssl req -x509 -newkey rsa:2048 -keyout cert.key -out cert.crt -days 365 -nodes


.. _asyncio: https://docs.python.org/3/library/asyncio.html
.. _OpenSSL: https://openssl-library.org/source/index.html
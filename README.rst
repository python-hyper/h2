===============================
hyper-h2: HTTP/2 Protocol Stack
===============================

.. image:: https://raw.github.com/Lukasa/hyper/development/docs/source/images/hyper.png

.. image:: https://travis-ci.org/python-hyper/hyper-h2.png?branch=master
    :target: https://travis-ci.org/Lukasa/hyper

This repository contains a pure-Python implementation of a HTTP/2 protocol
stack. It's written from the ground up to be embeddable in whatever program you
choose to use, ensuring that you can speak HTTP/2 regardless of your
programming paradigm.

You use it like this::

    import h2

    conn = h2.Connection()
    frames, stream_id = conn.send_headers(headers)
    data_frames = conn.send_data(stream_id, data)
    response_headers = conn.recv_header_frames(received_header_frames)
    response_data = conn.recv_data_frames(received_data_frames)


This repository does not provide a parsing layer, a network layer, or any rules
about concurrency. Instead, it's a purely in-memory solution, defined in terms
of data actions and HTTP/2 frames. This is one building block of a full Python
HTTP implementation.

Contributing
============

``hyper-h2`` welcomes contributions from anyone! Unlike many other projects we
are happy to accept cosmetic contributions and small contributions, in addition
to large feature requests and changes.

Before you contribute (either by opening an issue or filing a pull request),
please `read the contribution guidelines`_.

.. _read the contribution guidelines: http://hyper.readthedocs.org/en/development/contributing.html

License
=======

``hyper-h2`` is made available under the MIT License. For more details, see the
``LICENSE`` file in the repository.

Authors
=======

``hyper`` is maintained by Cory Benfield, with contributions from others. For
more details about the contributors, please see ``CONTRIBUTORS.rst``.

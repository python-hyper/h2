Release Notes
=============

This document contains release notes for Hyper-h2. In addition to the
:ref:`detailed-release-notes` found at the bottom of this document, this
document also includes a high-level prose overview of each major release after
1.0.0.

High Level Notes
----------------

2.0.0: 25 January 2016
~~~~~~~~~~~~~~~~~~~~~~

The Hyper-h2 team and the Hyper project are delighted to announce the release
of Hyper-h2 version 2.0.0! This is an enormous release that contains a gigantic
collection of new features and fixes, with the goal of making it easier than
ever to use Hyper-h2 to build a compliant HTTP/2 server or client.

An enormous chunk of this work has been focused on tighter enforcement of
restrictions in RFC 7540, ensuring that we correctly police the actions of
remote peers, and error appropriately when those peers violate the
specification. Several of these constitute breaking changes, becuase data that
was previously received and handled without obvious error now raises
``ProtocolError`` exceptions and causes the connection to be terminated.

Additionally, the public API was cleaned up and had several helper methods that
had been inavertently exposed removed from the public API. The team wants to
stress that while Hyper-h2 follows semantic versioning, the guarantees of
semver apply only to the public API as documented in :doc:`api`. Reducing the
surface area of these APIs makes it easier for us to continue to ensure that
the guarantees of semver are respected on our public API.

We also attempted to clear up some of the warts that had appeared in the API,
and add features that are helpful for implementing HTTP/2 endpoints. For
example, the :class:`H2Connection <h2.connection.H2Connection>` object now
exposes a method for generating the next stream ID that your client or server
can use to initiate a connection (:meth:`get_next_available_stream_id
<h2.connection.H2Connection.get_next_available_stream_id>`). We also removed
some needless return values that were guaranteed to return empty lists, which
were an attempt to make a forward-looking guarantee that was entirely unneeded.

Altogether, this has been an extremely productive period for Hyper-h2, and a
lot of great work has been done by the community. To that end, we'd also like
to extend a great thankyou to those contributers who made their first contribution
to the project between release 1.0.0 and 2.0.0. Many thanks to:
`Thomas Kriechbaumer`_, `Alex Chan`_, `Maximilian Hils`_, and `Glyph`_. For a
full historical list of contributors, see :doc:`contributors`.

We're looking forward to the next few months of Python HTTP/2 work, and hoping
that you'll find lots of excellent HTTP/2 applications to build with Hyper-h2!


.. _Thomas Kriechbaumer: https://github.com/Kriechi
.. _Alex Chan: https://github.com/alexwlchan
.. _Maximilian Hils: https://github.com/mhils
.. _Glyph: https://github.com/glyph


.. _detailed-release-notes:
.. include:: ../../HISTORY.rst

Hyper-h2 API
============

This document details the API of Hyper-h2.

Connection
----------

.. autoclass:: h2.connection.H2Connection
   :members:


.. _h2-events-api:

Events
------

.. autoclass:: h2.events.RequestReceived
   :members:

.. autoclass:: h2.events.ResponseReceived
   :members:

.. autoclass:: h2.events.TrailersReceived
   :members:

.. autoclass:: h2.events.DataReceived
   :members:

.. autoclass:: h2.events.WindowUpdated
   :members:

.. autoclass:: h2.events.RemoteSettingsChanged
   :members:

.. autoclass:: h2.events.PingAcknowledged
   :members:

.. autoclass:: h2.events.StreamEnded
   :members:

.. autoclass:: h2.events.StreamReset
   :members:

.. autoclass:: h2.events.PushedStreamReceived
   :members:

.. autoclass:: h2.events.SettingsAcknowledged
   :members:


Settings
--------

.. autoclass:: h2.settings.Settings
   :inherited-members:

.. autoclass:: h2.settings.ChangedSetting
   :members:

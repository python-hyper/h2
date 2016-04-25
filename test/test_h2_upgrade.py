# -*- coding: utf-8 -*-
"""
test_h2_upgrade.py
~~~~~~~~~~~~~~~~~~

This module contains tests that exercise the HTTP Upgrade functionality of
hyper-h2, ensuring that clients and servers can upgrade their plaintext
HTTP/1.1 connections to HTTP/2.
"""
import base64

import h2.connection


class TestClientUpgrade(object):
    """
    Tests of the client-side of the HTTP/2 upgrade dance.
    """
    def test_returns_http2_settings(self, frame_factory):
        """
        Calling initiate_upgrade_connection returns a base64url encoded
        Settings frame with the settings used by the connection.
        """
        conn = h2.connection.H2Connection()
        data = conn.initiate_upgrade_connection()

        # The base64 encoding must not be padded.
        assert not data.endswith(b'=')

        # However, SETTINGS frames should never need to be padded.
        decoded_frame = base64.urlsafe_b64decode(data)
        expected_frame = frame_factory.build_settings_frame(
            settings=conn.local_settings
        )
        assert decoded_frame == expected_frame.serialize()



class TestServerUpgrade(object):
    """
    Tests of the server-side of the HTTP/2 upgrade dance.
    """
    def test_returns_nothing(self, frame_factory):
        """
        Calling initiate_upgrade_connection returns nothing.
        """
        conn = h2.connection.H2Connection(client_side=False)
        curl_header = "AAMAAABkAAQAAP__"
        data = conn.initiate_upgrade_connection(curl_header)
        assert data is None

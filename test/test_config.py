# -*- coding: utf-8 -*-
"""
test_config
~~~~~~~~~~~

Test the configuration object.
"""
import pytest

import h2.config


class TestH2Config(object):
    """
    Tests of the H2 config object.
    """
    def test_defaults(self):
        """
        The default values of the HTTP/2 config object are sensible.
        """
        config = h2.config.H2Configuration()
        assert config.client_side
        assert config.header_encoding == 'utf-8'

    @pytest.mark.parametrize('client_side', [None, 'False', 1])
    def test_client_side_must_be_bool(self, client_side):
        """
        The value of the ``client_side`` setting must be a boolean.
        """
        config = h2.config.H2Configuration()

        with pytest.raises(ValueError):
            config.client_side = client_side

    @pytest.mark.parametrize('client_side', [True, False])
    def test_client_side_is_reflected(self, client_side):
        """
        The value of ``client_side``, when set, is reflected in the value.
        """
        config = h2.config.H2Configuration()
        config.client_side = client_side
        assert config.client_side == client_side

    @pytest.mark.parametrize('header_encoding', [True, 1, object()])
    def test_header_encoding_must_be_false_str_none(self, header_encoding):
        """
        The value of the ``header_encoding`` setting must be False, a string,
        or None.
        """
        config = h2.config.H2Configuration()

        with pytest.raises(ValueError):
            config.header_encoding = header_encoding

    @pytest.mark.parametrize('header_encoding', [False, 'ascii', None])
    def test_header_encoding_is_reflected(self, header_encoding):
        """
        The value of ``header_encoding``, when set, is reflected in the value.
        """
        config = h2.config.H2Configuration()
        config.header_encoding = header_encoding
        assert config.header_encoding == header_encoding

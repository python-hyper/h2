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

    boolean_config_options = [
        'client_side',
        'validate_sent_headers',
        'normalize_sent_headers',
        'validate_inbound_headers'
    ]

    @pytest.mark.parametrize('option_name', boolean_config_options)
    @pytest.mark.parametrize('value', [None, 'False', 1])
    def test_boolean_config_options_reject_non_bools(self, option_name, value):
        """
        The boolean config options raise an error if you try to set a value
        that isn't a boolean.
        """
        config = h2.config.H2Configuration()

        with pytest.raises(ValueError):
            setattr(config, option_name, value)

    @pytest.mark.parametrize('option_name', boolean_config_options)
    @pytest.mark.parametrize('value', [True, False])
    def test_boolean_config_option_is_reflected(self, option_name, value):
        """
        The value of the boolean config options, when set, is reflected
        in the value.
        """
        config = h2.config.H2Configuration()
        setattr(config, option_name, value)
        assert getattr(config, option_name) == value

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

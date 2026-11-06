"""
Test the configuration object.
"""
from __future__ import annotations

import io
import logging

import pytest

import h2.config


class TestH2Config:
    """
    Tests of the H2 config object.
    """

    def test_defaults(self) -> None:
        """
        The default values of the HTTP/2 config object are sensible.
        """
        config = h2.config.H2Configuration()
        assert config.client_side
        assert config.header_encoding is None
        assert isinstance(config.logger, h2.config.DummyLogger)

    boolean_config_options = [
        "client_side",
        "validate_outbound_headers",
        "normalize_outbound_headers",
        "validate_inbound_headers",
        "normalize_inbound_headers",
    ]

    @pytest.mark.parametrize("option_name", boolean_config_options)
    @pytest.mark.parametrize("value", [None, "False", 1])
    def test_boolean_config_options_reject_non_bools_init(
        self, option_name, value,
    ) -> None:
        """
        The boolean config options raise an error if you try to set a value
        that isn't a boolean via the initializer.
        """
        with pytest.raises(ValueError):
            h2.config.H2Configuration(**{option_name: value})

    @pytest.mark.parametrize("option_name", boolean_config_options)
    @pytest.mark.parametrize("value", [None, "False", 1])
    def test_boolean_config_options_reject_non_bools_attr(
        self, option_name, value,
    ) -> None:
        """
        The boolean config options raise an error if you try to set a value
        that isn't a boolean via attribute setter.
        """
        config = h2.config.H2Configuration()
        with pytest.raises(ValueError):
            setattr(config, option_name, value)

    @pytest.mark.parametrize("option_name", boolean_config_options)
    @pytest.mark.parametrize("value", [True, False])
    def test_boolean_config_option_is_reflected_init(self, option_name, value) -> None:
        """
        The value of the boolean config options, when set, is reflected
        in the value via the initializer.
        """
        config = h2.config.H2Configuration(**{option_name: value})
        assert getattr(config, option_name) == value

    @pytest.mark.parametrize("option_name", boolean_config_options)
    @pytest.mark.parametrize("value", [True, False])
    def test_boolean_config_option_is_reflected_attr(self, option_name, value) -> None:
        """
        The value of the boolean config options, when set, is reflected
        in the value via attribute setter.
        """
        config = h2.config.H2Configuration()
        setattr(config, option_name, value)
        assert getattr(config, option_name) == value

    @pytest.mark.parametrize("header_encoding", [True, 1, object()])
    def test_header_encoding_must_be_false_str_none_init(
        self, header_encoding,
    ) -> None:
        """
        The value of the ``header_encoding`` setting must be False, a string,
        or None via the initializer.
        """
        with pytest.raises(ValueError):
            h2.config.H2Configuration(header_encoding=header_encoding)

    @pytest.mark.parametrize("header_encoding", [True, 1, object()])
    def test_header_encoding_must_be_false_str_none_attr(
        self, header_encoding,
    ) -> None:
        """
        The value of the ``header_encoding`` setting must be False, a string,
        or None via attribute setter.
        """
        config = h2.config.H2Configuration()
        with pytest.raises(ValueError):
            config.header_encoding = header_encoding

    @pytest.mark.parametrize("header_encoding", [False, "ascii", None])
    def test_header_encoding_is_reflected_init(self, header_encoding) -> None:
        """
        The value of ``header_encoding``, when set, is reflected in the value
        via the initializer.
        """
        config = h2.config.H2Configuration(header_encoding=header_encoding)
        assert config.header_encoding == header_encoding

    @pytest.mark.parametrize("header_encoding", [False, "ascii", None])
    def test_header_encoding_is_reflected_attr(self, header_encoding) -> None:
        """
        The value of ``header_encoding``, when set, is reflected in the value
        via the attribute setter.
        """
        config = h2.config.H2Configuration()
        config.header_encoding = header_encoding
        assert config.header_encoding == header_encoding

    def test_logger_instance_is_reflected(self) -> None:
        """
        The value of ``logger``, when set, is reflected in the value.
        """
        logger = logging.getLogger("hyper-h2.test")
        config = h2.config.H2Configuration()
        config.logger = logger
        assert config.logger is logger

    def test_falsey_logger_is_used(self) -> None:
        messages: list[str] = []

        class EmptyLogger(h2.config.DummyLogger):
            def __len__(self) -> int:
                return len(messages)

            def debug(self, *args: object, **kwargs: object) -> None:
                messages.append("debug")

            def trace(self, *args: object, **kwargs: object) -> None:
                messages.append("trace")

        logger = EmptyLogger()
        assert not logger
        config = h2.config.H2Configuration(logger=logger)

        assert config.logger is logger
        config.logger.debug("owned debug")
        config.logger.trace("owned trace")
        assert messages == ["debug", "trace"]

    @pytest.mark.parametrize("trace_level", [False, True])
    def test_falsey_file_is_used(self, capsys, trace_level) -> None:
        class FalseyFile(io.StringIO):
            def __bool__(self) -> bool:
                return False

        with FalseyFile() as output:
            logger = h2.config.OutputLogger(file=output, trace_level=trace_level)
            logger.debug("owned debug")
            logger.trace("owned trace")

            expected = "h2 (debug): owned debug\n"
            if trace_level:
                expected += "h2 (trace): owned trace\n"
            assert output.getvalue() == expected
            assert not output.closed
            assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("trace_level", [False, True])
    def test_output_logger(self, capsys, trace_level) -> None:
        logger = h2.config.OutputLogger(trace_level=trace_level)

        logger.debug("This is a debug message %d.", 123)
        logger.trace("This is a trace message %d.", 123)
        captured = capsys.readouterr()
        assert "h2 (debug): This is a debug message 123.\n" in captured.err
        if trace_level:
            assert "h2 (trace): This is a trace message 123.\n" in captured.err
        else:
            assert "h2 (trace): This is a trace message 123.\n" not in captured.err

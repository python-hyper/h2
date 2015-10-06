# -*- coding: utf-8 -*-
"""
test_settings
~~~~~~~~~~~~~

Test the Settings object.
"""
import pytest

import h2.settings

from hyperframe.frame import SettingsFrame


class TestSettings(object):
    """
    Test the Settings object behaves as expected.
    """
    def test_settings_defaults_client(self):
        """
        The Settings object begins with the appropriate defaults for clients.
        """
        s = h2.settings.Settings(client=True)

        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 4096
        assert s[SettingsFrame.ENABLE_PUSH] == 1
        assert s[SettingsFrame.INITIAL_WINDOW_SIZE] == 65535
        assert s[SettingsFrame.SETTINGS_MAX_FRAME_SIZE] == 16384

    def test_settings_defaults_server(self):
        """
        The Settings object begins with the appropriate defaults for servers.
        """
        s = h2.settings.Settings(client=False)

        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 4096
        assert s[SettingsFrame.ENABLE_PUSH] == 0
        assert s[SettingsFrame.INITIAL_WINDOW_SIZE] == 65535
        assert s[SettingsFrame.SETTINGS_MAX_FRAME_SIZE] == 16384

    def test_applying_value_doesnt_take_effect_immediately(self):
        """
        When a value is applied to the settings object, it doesn't immediately
        take effect.
        """
        s = h2.settings.Settings(client=True)
        s[SettingsFrame.HEADER_TABLE_SIZE] == 8000

        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 4096

    def test_acknowledging_values(self):
        """
        When we acknowledge settings, the values change.
        """
        s = h2.settings.Settings(client=True)
        old_settings = dict(s)

        new_settings = {
            SettingsFrame.HEADER_TABLE_SIZE: 4000,
            SettingsFrame.ENABLE_PUSH: 0,
            SettingsFrame.INITIAL_WINDOW_SIZE: 60,
            SettingsFrame.SETTINGS_MAX_FRAME_SIZE: 30,
        }
        s.update(new_settings)

        assert dict(s) == old_settings
        s.acknowledge()
        assert dict(s) == new_settings

    def test_acknowledging_returns_the_changed_settings(self):
        """
        Acknowledging settings returns the changes.
        """
        s = h2.settings.Settings(client=True)
        s[SettingsFrame.HEADER_TABLE_SIZE] = 8000
        s[SettingsFrame.ENABLE_PUSH] = 0

        changes = s.acknowledge()
        assert len(changes) == 2

        table_size_change = changes[SettingsFrame.HEADER_TABLE_SIZE]
        push_change = changes[SettingsFrame.ENABLE_PUSH]

        assert table_size_change.setting == SettingsFrame.HEADER_TABLE_SIZE
        assert table_size_change.original_value == 4096
        assert table_size_change.new_value == 8000

        assert push_change.setting == SettingsFrame.ENABLE_PUSH
        assert push_change.original_value == 1
        assert push_change.new_value == 0

    def test_acknowledging_only_returns_changed_settings(self):
        """
        Acknowledging settings does not return unchanged settings.
        """
        s = h2.settings.Settings(client=True)
        s[SettingsFrame.INITIAL_WINDOW_SIZE] = 70

        changes = s.acknowledge()
        assert len(changes) == 1
        assert list(changes.keys()) == [SettingsFrame.INITIAL_WINDOW_SIZE]

    def test_deleting_values_deletes_all_of_them(self):
        """
        When we delete a key we lose all state about it.
        """
        s = h2.settings.Settings(client=True)
        s[SettingsFrame.HEADER_TABLE_SIZE] == 8000

        del s[SettingsFrame.HEADER_TABLE_SIZE]

        with pytest.raises(KeyError):
            s[SettingsFrame.HEADER_TABLE_SIZE]

    def test_length_correctly_reported(self):
        """
        Length is related only to the number of keys.
        """
        s = h2.settings.Settings(client=True)
        assert len(s) == 4

        s[SettingsFrame.HEADER_TABLE_SIZE] == 8000
        assert len(s) == 4

        s.acknowledge()
        assert len(s) == 4

        del s[SettingsFrame.HEADER_TABLE_SIZE]
        assert len(s) == 3

    def test_new_values_work(self):
        """
        New values initially don't appear
        """
        s = h2.settings.Settings(client=True)
        s[80] = 81

        with pytest.raises(KeyError):
            s[80]

    def test_new_values_follow_basic_acknowledgement_rules(self):
        """
        A new value properly appears when acknowledged.
        """
        s = h2.settings.Settings(client=True)
        s[80] = 81
        changed_settings = s.acknowledge()

        assert s[80] == 81
        assert len(changed_settings) == 1

        changed = changed_settings[80]
        assert changed.setting == 80
        assert changed.original_value is None
        assert changed.new_value == 81

    def test_single_values_arent_affected_by_acknowledgement(self):
        """
        When acknowledged, unchanged settings remain unchanged.
        """
        s = h2.settings.Settings(client=True)
        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 4096

        s.acknowledge()
        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 4096

    def test_settings_getters(self):
        """
        Getters exist for well-known settings.
        """
        s = h2.settings.Settings(client=True)

        assert s.header_table_size == s[SettingsFrame.HEADER_TABLE_SIZE]
        assert s.enable_push == s[SettingsFrame.ENABLE_PUSH]
        assert s.initial_window_size == s[SettingsFrame.INITIAL_WINDOW_SIZE]
        assert s.max_frame_size == s[SettingsFrame.SETTINGS_MAX_FRAME_SIZE]
        assert s.max_concurrent_streams == 2**32 + 1  # A sensible default.

    def test_settings_setters(self):
        """
        Setters exist for well-known settings.
        """
        s = h2.settings.Settings(client=True)

        s.header_table_size = 0
        s.enable_push = 1
        s.initial_window_size = 2
        s.max_frame_size = 3
        s.max_concurrent_streams = 4

        s.acknowledge()
        assert s[SettingsFrame.HEADER_TABLE_SIZE] == 0
        assert s[SettingsFrame.ENABLE_PUSH] == 1
        assert s[SettingsFrame.INITIAL_WINDOW_SIZE] == 2
        assert s[SettingsFrame.SETTINGS_MAX_FRAME_SIZE] == 3
        assert s[SettingsFrame.MAX_CONCURRENT_STREAMS] == 4

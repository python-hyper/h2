# -*- coding: utf-8 -*-
"""
test_events.py
~~~~~~~~~~~~~~

Specific tests for any function that is logically self-contained as part of
events.py.
"""
from hypothesis import given
from hypothesis.strategies import (
    integers, lists, tuples
)

import h2.events


# We define a fairly complex Hypothesis strategy here. We want to build a list
# of two tuples of (Setting, value). For Setting we want to make sure we can
# handle settings that the rest of hyper knows nothing about, so we want to
# use integers from 0 to (2**16-1). For values, they're from 0 to (2**32-1).
# Define that strategy here for clarity.
SETTINGS_STRATEGY = lists(
    tuples(
        integers(min_value=0, max_value=2**16-1),
        integers(min_value=0, max_value=2**32-1),
    )
)


class TestRemoteSettingsChanged(object):
    """
    Validate the function of the RemoteSettingsChanged event.
    """
    @given(SETTINGS_STRATEGY)
    def test_building_settings_from_scratch(self, settings_list):
        """
        Missing old settings are defaulted to None.
        """
        settings_dict = dict(settings_list)
        e = h2.events.RemoteSettingsChanged.from_settings(
            old_settings={},
            new_settings=settings_dict,
        )

        for setting, new_value in settings_dict.items():
            assert e.changed_settings[setting].setting == setting
            assert e.changed_settings[setting].original_value is None
            assert e.changed_settings[setting].new_value == new_value

    @given(SETTINGS_STRATEGY, SETTINGS_STRATEGY)
    def test_only_reports_changed_settings(self,
                                           old_settings_list,
                                           new_settings_list):
        """
        Settings that were not changed are not reported.
        """
        old_settings_dict = dict(old_settings_list)
        new_settings_dict = dict(new_settings_list)
        e = h2.events.RemoteSettingsChanged.from_settings(
            old_settings=old_settings_dict,
            new_settings=new_settings_dict,
        )

        assert len(e.changed_settings) == len(new_settings_dict)
        assert (
            sorted(list(e.changed_settings.keys())) ==
            sorted(list(new_settings_dict.keys()))
        )

    @given(SETTINGS_STRATEGY, SETTINGS_STRATEGY)
    def test_correctly_reports_changed_settings(self,
                                                old_settings_list,
                                                new_settings_list):
        """
        Settings that are changed are correctly reported.
        """
        old_settings_dict = dict(old_settings_list)
        new_settings_dict = dict(new_settings_list)
        e = h2.events.RemoteSettingsChanged.from_settings(
            old_settings=old_settings_dict,
            new_settings=new_settings_dict,
        )

        for setting, new_value in new_settings_dict.items():
            original_value = old_settings_dict.get(setting)
            assert e.changed_settings[setting].setting == setting
            assert e.changed_settings[setting].original_value == original_value
            assert e.changed_settings[setting].new_value == new_value

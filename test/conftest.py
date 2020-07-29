# -*- coding: utf-8 -*-
import pytest
from hypothesis import settings, HealthCheck

from . import helpers


@pytest.fixture
def frame_factory():
    return helpers.FrameFactory()

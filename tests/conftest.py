import pytest

from . import helpers


@pytest.fixture
def frame_factory():
    return helpers.FrameFactory()

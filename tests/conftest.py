import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import load_config  # noqa: E402


@pytest.fixture
def cfg():
    c = load_config()
    c.simulate_feed = True
    c.mode = "paper"
    return c

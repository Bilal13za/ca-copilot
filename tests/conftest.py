import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets a fresh, isolated data directory."""
    monkeypatch.setenv("CA_COPILOT_DATA_DIR", str(tmp_path / "data"))
    yield


@pytest.fixture()
def sample_data():
    return ROOT / "sample_data"

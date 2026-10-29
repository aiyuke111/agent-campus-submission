import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from helpers import build_agent, load_request  # noqa: E402
from src.tools import Toolbox  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")


@pytest.fixture()
def store(tmp_path):
    return str(tmp_path / "drafts.json")


@pytest.fixture()
def run(store):
    def _run(name: str, inject=None, policy=None, **kwargs):
        return build_agent(store, inject=inject, policy=policy, **kwargs).run(load_request(name))

    return _run


@pytest.fixture()
def toolbox(store):
    return Toolbox(DATA_DIR, store_path=store)

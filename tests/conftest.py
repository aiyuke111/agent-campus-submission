import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.agent import Agent
from src.policy import MockPolicy
from src.schemas import Request
from src.tools import Toolbox

DATA_DIR = os.path.join(ROOT, "data")
INPUT_DIR = os.path.join(ROOT, "examples", "inputs")


def load_request(name: str) -> Request:
    with open(os.path.join(INPUT_DIR, f"{name}.json"), "r", encoding="utf-8") as f:
        return Request.from_dict(json.load(f))


def build_agent(store_path: str, inject=None, max_steps: int = 8, max_tool_calls: int = 12) -> Agent:
    toolbox = Toolbox(DATA_DIR, store_path=store_path, inject=inject or {})
    return Agent(toolbox, MockPolicy(), max_steps=max_steps, max_tool_calls=max_tool_calls)


@pytest.fixture()
def store(tmp_path):
    return str(tmp_path / "drafts.json")


@pytest.fixture()
def run(store):
    def _run(name: str, inject=None, **kwargs):
        return build_agent(store, inject=inject, **kwargs).run(load_request(name))

    return _run


@pytest.fixture()
def toolbox(store):
    return Toolbox(DATA_DIR, store_path=store)

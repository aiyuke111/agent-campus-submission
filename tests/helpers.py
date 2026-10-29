import json
import os
import sys

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


def build_agent(store_path: str, inject=None, max_steps: int = 8, max_tool_calls: int = 12,
                policy=None) -> Agent:
    toolbox = Toolbox(DATA_DIR, store_path=store_path, inject=inject or {})
    if policy is None:
        days = toolbox.slots_cfg.get("search_days")
        policy = MockPolicy(search_days=int(days) if days is not None else None)
    return Agent(toolbox, policy, max_steps=max_steps, max_tool_calls=max_tool_calls)


def run_request(store_path: str, name: str, **kwargs):
    return build_agent(store_path, **kwargs).run(load_request(name))

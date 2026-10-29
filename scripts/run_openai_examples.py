"""用真实 OpenAI 兼容模型跑多条执行路径，生成 Trace。

需要环境变量：
  OPENAI_API_KEY / DEEPSEEK_API_KEY
  OPENAI_BASE_URL（默认 https://api.deepseek.com/v1）
  OPENAI_MODEL（默认 deepseek-chat）

运行：python scripts/run_openai_examples.py
输出：examples/traces/openai/*.result.json / *.trace.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.agent import Agent
from src.llm.openai_policy import OpenAIPolicy
from src.schemas import Request
from src.tools import Toolbox

SCENARIOS = [
    ("normal", "request_M05_normal.json"),
    ("conflict", "request_M01_conflict.json"),
    ("risk", "request_M03_risk.json"),
]


def main() -> int:
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")):
        print("缺少 OPENAI_API_KEY / DEEPSEEK_API_KEY", file=sys.stderr)
        return 2
    outdir = os.path.join(ROOT, "examples", "traces", "openai")
    os.makedirs(outdir, exist_ok=True)
    store = os.path.join(outdir, "drafts.json")
    if os.path.exists(store):
        os.remove(store)

    for name, filename in SCENARIOS:
        with open(os.path.join(ROOT, "examples", "inputs", filename), "r", encoding="utf-8-sig") as f:
            request = Request.from_dict(json.load(f))
        toolbox = Toolbox(os.path.join(ROOT, "data"), store_path=store)
        agent = Agent(toolbox, OpenAIPolicy(), max_steps=10, max_tool_calls=16)
        out = agent.run(request)
        result, trace = out["result"], out["trace"]
        with open(os.path.join(outdir, f"openai_{name}.result.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        with open(os.path.join(outdir, f"openai_{name}.trace.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        print(f"{name}: status={result['status']} steps={result['steps_used']} tools={result['tool_calls_used']} "
              f"violations={len(result.get('claim_violations') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

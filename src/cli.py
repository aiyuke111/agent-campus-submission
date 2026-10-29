"""命令行入口。

用法示例：
  python -m src.cli --request examples/inputs/request_M01_conflict.json --outdir examples/outputs
  python -m src.cli --request examples/inputs/request_M05_normal.json --inject save_fail --outdir examples/outputs
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from .agent import Agent
from .policy import MockPolicy
from .schemas import Request
from .tools import Toolbox


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="素材审核与发布排期 Agent（仅生成草稿，不发布）")
    p.add_argument("--request", required=True, help="请求 JSON 路径")
    p.add_argument("--data", default="data", help="数据目录，默认 data/")
    p.add_argument("--store", default=None, help="草稿存储路径，默认 <data>/drafts.json")
    p.add_argument("--inject", choices=["none", "save_fail"], default="none",
                   help="故障注入：save_fail 时 save_draft 必定失败")
    p.add_argument("--policy", choices=["mock"], default="mock", help="决策策略；默认离线 mock")
    p.add_argument("--max-steps", type=int, default=8)
    p.add_argument("--max-tool-calls", type=int, default=12)
    p.add_argument("--outdir", default=None, help="结果与 Trace 输出目录")
    p.add_argument("--tag", default="", help="输出文件名后缀，避免重复提交时覆盖")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    request = Request.from_dict(_load_json(args.request))
    inject = {"save_fail": True} if args.inject == "save_fail" else {}
    store = args.store or os.path.join(args.data, "drafts.json")

    toolbox = Toolbox(args.data, store_path=store, inject=inject)
    policy = MockPolicy()
    agent = Agent(toolbox, policy, max_steps=args.max_steps, max_tool_calls=args.max_tool_calls)
    out = agent.run(request)

    print(json.dumps(out["result"], ensure_ascii=False, indent=2))

    if args.outdir:
        stem = os.path.splitext(os.path.basename(args.request))[0]
        suffix = f".{args.tag}" if args.tag else ""
        _write_json(os.path.join(args.outdir, f"{stem}{suffix}.result.json"), out["result"])
        _write_json(os.path.join(args.outdir, f"{stem}{suffix}.trace.json"), out["trace"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""命令行入口。

用法示例：
  python -m src.cli --request examples/inputs/request_M01_conflict.json --outdir examples/outputs
  python -m src.cli --request a.json --request b.json --outdir examples/outputs   # 批量
  python -m src.cli --request examples/inputs/request_M05_normal.json --inject save_fail
  python -m src.cli --request examples/inputs/request_M05_normal.json --policy openai

退出码：0 = 正常执行（无论业务结论）；2 = 请求文件无法读取或系统配置错误。
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .agent import Agent
from .errors import ToolError
from .policy import MockPolicy
from .schemas import Request
from .tools import Toolbox


def _load_json(path: str) -> Dict[str, Any]:
    # utf-8-sig：兼容 Windows 下带 BOM 的 JSON 文件
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _emit_error(reason: str, outdir: Optional[str], tag: str, request_path: str) -> int:
    payload = {
        "status": "ERROR",
        "review_status": "ERROR",
        "reason": reason,
        "published": False,
        "draft": {"saved": False, "draft_id": None, "duplicate": False},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if outdir:
        stem = os.path.splitext(os.path.basename(request_path))[0]
        suffix = f".{tag}" if tag else ""
        _write_json(os.path.join(outdir, f"{stem}{suffix}.result.json"), payload)
    return 2


def _build_policy(args: argparse.Namespace, toolbox: Toolbox):
    if args.policy == "openai":
        from .llm.openai_policy import OpenAIPolicy
        return OpenAIPolicy(model=args.model)
    days = toolbox.slots_cfg.get("search_days")
    return MockPolicy(search_days=int(days) if days is not None else None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="素材审核与发布排期 Agent（仅生成草稿，不发布）")
    p.add_argument("--request", action="append", required=True,
                   help="请求 JSON 路径，可重复传入以批量处理")
    p.add_argument("--data", default="data", help="数据目录，默认 data/")
    p.add_argument("--store", default=None, help="草稿存储路径，默认 <data>/drafts.json")
    p.add_argument("--inject", choices=["none", "save_fail"], default="none",
                   help="故障注入：save_fail 时 save_draft 必定失败")
    p.add_argument("--policy", choices=["mock", "openai"], default="mock",
                   help="决策策略：mock=离线可复现；openai=真实模型（需 OPENAI_API_KEY）")
    p.add_argument("--model", default="gpt-4o-mini", help="--policy openai 时的模型名")
    p.add_argument("--max-steps", type=int, default=8)
    p.add_argument("--max-tool-calls", type=int, default=12)
    p.add_argument("--outdir", default=None, help="结果与 Trace 输出目录")
    p.add_argument("--tag", default="", help="输出文件名后缀，避免重复提交时覆盖")
    return p


def _run_one(args: argparse.Namespace, request_path: str) -> int:
    try:
        request_data = _load_json(request_path)
    except (OSError, json.JSONDecodeError) as exc:
        return _emit_error(f"请求文件无法读取: {exc}", args.outdir, args.tag, request_path)

    request = Request.from_dict(request_data)
    inject = {"save_fail": True} if args.inject == "save_fail" else {}
    store = args.store or os.path.join(args.data, "drafts.json")

    try:
        toolbox = Toolbox(args.data, store_path=store, inject=inject)
        agent = Agent(toolbox, _build_policy(args, toolbox),
                      max_steps=args.max_steps, max_tool_calls=args.max_tool_calls)
        out = agent.run(request)
    except ToolError as exc:
        return _emit_error(f"系统错误: {exc.message}", args.outdir, args.tag, request_path)
    except Exception as exc:  # noqa: BLE001 - CLI 兜底，避免 traceback
        return _emit_error(f"未预期错误: {exc}", args.outdir, args.tag, request_path)

    print(json.dumps(out["result"], ensure_ascii=False, indent=2))

    if args.outdir:
        stem = os.path.splitext(os.path.basename(request_path))[0]
        suffix = f".{args.tag}" if args.tag else ""
        _write_json(os.path.join(args.outdir, f"{stem}{suffix}.result.json"), out["result"])
        _write_json(os.path.join(args.outdir, f"{stem}{suffix}.trace.json"), out["trace"])
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if len(args.request) > 1:
        print(f"# 批量处理 {len(args.request)} 个请求，草稿库: {args.store or os.path.join(args.data, 'drafts.json')}")
    for path in args.request:
        code = _run_one(args, path)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Agent 主循环：决策 → 调用工具 → 观察 → 再决策，带步数与工具调用上限。

只做草稿与确认，不包含任何发布动作。
"""

import uuid
from typing import Any, Dict, List, Tuple

from . import guards
from .errors import ToolError
from .schemas import Action, Request, ReviewStatus, Status


class Agent:
    def __init__(self, toolbox, policy, max_steps: int = 8, max_tool_calls: int = 12):
        self.toolbox = toolbox
        self.policy = policy
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls

    # ---------- public ----------
    def run(self, request: Request) -> Dict[str, Any]:
        guards.assert_request(request)
        trace_id = "T" + uuid.uuid4().hex[:10]
        ctx: Dict[str, Any] = {
            "request": request,
            "material": None,
            "material_error": None,
            "risks": None,
            "slot_info": None,
            "proposed": None,
            "draft_result": None,
            "save_error": None,
            "tool_error": None,
            "dates_tried": [request.publish_date],
        }
        steps: List[Dict[str, Any]] = []
        tool_calls = 0

        while len(steps) < self.max_steps:
            decision = self.policy.decide(ctx)
            guards.assert_action_allowed(decision["action"])

            # 模型决定结束
            if decision["action"] == Action.FINISH:
                args = decision["args"]
                steps.append(self._step(len(steps) + 1, decision,
                                        {"status": args["status"], "review_status": args["review_status"],
                                         "reason": args["reason"]}))
                return self._wrap(self._result(request, ctx, args, steps, tool_calls, trace_id),
                                  request, steps, tool_calls, trace_id)

            # 工具调用预算
            if tool_calls >= self.max_tool_calls:
                limit_decision = {
                    "action": "limit_reached",
                    "args": {"limit": "max_tool_calls", "value": self.max_tool_calls},
                    "decision_basis": "达到工具调用上限，停止执行并返回未完成",
                }
                steps.append(self._step(len(steps) + 1, limit_decision, {"status": Status.INCOMPLETE}))
                return self._wrap(self._incomplete(request, ctx, steps, tool_calls, trace_id, "max_tool_calls"),
                                  request, steps, tool_calls, trace_id)

            observation, error = self._execute(decision, request, ctx)
            tool_calls += 1
            steps.append(self._step(len(steps) + 1, decision, observation, error))

        # 步数上限
        return self._wrap(self._incomplete(request, ctx, steps, tool_calls, trace_id, "max_steps"),
                          request, steps, tool_calls, trace_id)

    # ---------- internals ----------
    def _execute(self, decision: Dict[str, Any], request: Request,
                 ctx: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        name = decision["action"]
        args = decision["args"]
        try:
            if name == Action.GET_MATERIAL:
                out = self.toolbox.get_material(args["material_id"])
                ctx["material"] = out
                return {"title": out["title"], "missing_fields": out["missing_fields"]}, None
            if name == Action.CHECK_RULES:
                out = self.toolbox.check_rules(args["material_id"])
                ctx["risks"] = out["risks"]
                return {"risks": out["risks"]}, None
            if name == Action.QUERY_SLOTS:
                out = self.toolbox.query_slots(args["date"], args["requested_time"])
                ctx["slot_info"] = out
                return {"date": out["date"], "date_exists": out["date_exists"],
                        "requested_free": out["requested"]["free"],
                        "available": out["available"], "candidates": out["candidates"]}, None
            if name == Action.SAVE_DRAFT:
                out = self.toolbox.save_draft(
                    material_id=request.material_id,
                    date=args["date"], time=args["time"],
                    requested_time=args["requested_time"], hard=args["hard"],
                )
                ctx["draft_result"] = out
                return {"saved": out["saved"], "draft_id": out["draft_id"], "duplicate": out["duplicate"]}, None
            raise RuntimeError(f"未知工具动作: {name}")
        except ToolError as exc:
            err = exc.to_dict()
            err["tool"] = name
            if name == Action.GET_MATERIAL:
                ctx["material_error"] = err
            elif name == Action.SAVE_DRAFT:
                ctx["save_error"] = err
            else:
                ctx["tool_error"] = err
            return {"error": err}, err

    def _step(self, index: int, decision: Dict[str, Any], observation: Dict[str, Any],
              error: Dict[str, Any] = None) -> Dict[str, Any]:
        step = {
            "step": index,
            "decision_basis": decision.get("decision_basis", ""),
            "action": decision["action"],
            "args": decision.get("args", {}),
            "observation": observation,
        }
        if error:
            step["error"] = error
        return step

    def _result(self, request: Request, ctx: Dict[str, Any], args: Dict[str, Any],
                steps: List[Dict[str, Any]], tool_calls: int, trace_id: str) -> Dict[str, Any]:
        proposed = ctx.get("proposed")
        draft = dict(ctx.get("draft_result") or {"saved": False, "draft_id": None, "duplicate": False})
        if ctx.get("save_error"):
            draft["saved"] = False
            draft["error"] = ctx["save_error"]
        suggested = None
        if proposed:
            suggested = {
                "date": proposed["date"],
                "time": proposed["time"],
                "alternative": proposed["alternative"],
                "hard_requirement_modified": False,
            }
        return {
            "trace_id": trace_id,
            "material_id": request.material_id,
            "review_status": args.get("review_status"),
            "status": args.get("status"),
            "reason": args.get("reason"),
            "risk_reasons": [r["reason"] for r in (ctx.get("risks") or [])],
            "risks": ctx.get("risks") or [],
            "requested_slot": {"date": request.publish_date, "time": request.publish_time, "hard": request.hard},
            "suggested_slot": suggested,
            "pending_items": args.get("pending", []),
            "draft": draft,
            "published": False,
            "steps_used": len(steps),
            "tool_calls_used": tool_calls,
            "limits": {"max_steps": self.max_steps, "max_tool_calls": self.max_tool_calls},
        }

    def _incomplete(self, request: Request, ctx: Dict[str, Any], steps: List[Dict[str, Any]],
                    tool_calls: int, trace_id: str, limit: str) -> Dict[str, Any]:
        args = {
            "status": Status.INCOMPLETE,
            "review_status": ReviewStatus.INCOMPLETE,
            "reason": f"达到 {limit} 上限，任务未完成，已保留已获取的结果",
            "pending": ["任务未完成，请缩短流程或放宽上限后重试"],
        }
        result = self._result(request, ctx, args, steps, tool_calls, trace_id)
        result["collected"] = {
            "material": ctx.get("material"),
            "risks": ctx.get("risks"),
            "slot_info": ctx.get("slot_info"),
        }
        return result

    def _wrap(self, result: Dict[str, Any], request: Request, steps: List[Dict[str, Any]],
              tool_calls: int, trace_id: str) -> Dict[str, Any]:
        for i in range(len(steps) - 1):
            steps[i]["next_action"] = steps[i + 1]["action"]
        if steps:
            steps[-1]["next_action"] = "end"
        trace = {
            "trace_id": trace_id,
            "policy": getattr(self.policy, "name", "unknown"),
            "request": {
                "material_id": request.material_id,
                "publish_date": request.publish_date,
                "publish_time": request.publish_time,
                "hard": request.hard,
                "operator": request.operator,
            },
            "limits": {"max_steps": self.max_steps, "max_tool_calls": self.max_tool_calls},
            "tool_calls_used": tool_calls,
            "steps": steps,
            "final_status": result["status"],
        }
        return {"result": result, "trace": trace}

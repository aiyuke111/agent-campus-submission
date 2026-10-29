"""Agent 主循环：决策 → 调用工具 → 观察 → 再决策，带步数与工具调用上限。

安全要点：
- 结束结论必须通过证据校验，模型不能虚报"已保存/已通过"；
- 工具动作必须满足前置条件，模型不能跳过审核直接保存；
- 模型输出异常（超时、非 JSON、缺字段）转成结构化 ERROR，不抛 traceback；
- 只做草稿与确认，不包含任何发布动作。
"""

import uuid
from typing import Any, Dict, List, Tuple

from . import guards
from .errors import PolicyError, RejectedAction, ToolError
from .schemas import Action, Request, ReviewStatus, Status


class Agent:
    def __init__(self, toolbox, policy, max_steps: int = 8, max_tool_calls: int = 12):
        self.toolbox = toolbox
        self.policy = policy
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls

    # ---------- public ----------
    def run(self, request: Request) -> Dict[str, Any]:
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
            # 1) 模型决策（异常必须结构化，不能让进程崩）
            try:
                decision = self.policy.decide(ctx)
            except Exception as exc:  # noqa: BLE001 - 任何模型异常都要转成结果
                error = PolicyError("POLICY_ERROR", f"模型调用失败: {exc}")
                steps.append(self._step(len(steps) + 1,
                                        {"action": "policy_error", "args": {}, "decision_basis": "模型调用异常"},
                                        {"error": error.to_dict()}))
                return self._wrap(self._error_result(request, ctx, steps, tool_calls, trace_id,
                                                     "模型调用失败，任务中止", [error.to_dict()]),
                                  request, steps, tool_calls, trace_id)

            # 2) 动作名与结构校验
            try:
                self._validate_decision(decision)
                guards.assert_action_allowed(decision["action"])
            except (RejectedAction, KeyError, TypeError) as exc:
                reason = getattr(exc, "message", str(exc))
                steps.append(self._step(len(steps) + 1, self._safe_decision(decision),
                                        {"rejected": reason}))
                return self._wrap(self._error_result(request, ctx, steps, tool_calls, trace_id,
                                                     f"动作被拒绝: {reason}",
                                                     [{"code": getattr(exc, "code", "DECISION_INVALID"),
                                                       "message": reason}]),
                                  request, steps, tool_calls, trace_id)

            # 3) 模型决定结束：结束结论必须先过证据校验
            if decision["action"] == Action.FINISH:
                final = self._validate_finish(ctx, decision.get("args", {}))
                steps.append(self._step(len(steps) + 1,
                                        {**decision, "args": final},
                                        {"status": final["status"], "review_status": final["review_status"]}))
                result = self._result(request, ctx, final, steps, tool_calls, trace_id)
                return self._wrap(result, request, steps, tool_calls, trace_id)

            # 4) 工具调用预算
            if tool_calls >= self.max_tool_calls:
                limit_decision = {
                    "action": "limit_reached",
                    "args": {"limit": "max_tool_calls", "value": self.max_tool_calls},
                    "decision_basis": "达到工具调用上限，停止执行并返回未完成",
                }
                steps.append(self._step(len(steps) + 1, limit_decision, {"status": Status.INCOMPLETE}))
                return self._wrap(self._incomplete(request, ctx, steps, tool_calls, trace_id, "max_tool_calls"),
                                  request, steps, tool_calls, trace_id)

            # 5) 前置条件守卫：不允许跳过审核/篡改参数
            try:
                guards.check_preconditions(decision["action"], decision.get("args", {}), ctx, request)
            except RejectedAction as exc:
                steps.append(self._step(len(steps) + 1, decision, {"rejected": exc.message}))
                return self._wrap(self._error_result(request, ctx, steps, tool_calls, trace_id,
                                                     f"动作被拒绝: {exc.message}",
                                                     [exc.to_dict()]),
                                  request, steps, tool_calls, trace_id)

            # 6) 执行工具
            observation, error = self._execute(decision, request, ctx)
            tool_calls += 1
            steps.append(self._step(len(steps) + 1, decision, observation, error))

        return self._wrap(self._incomplete(request, ctx, steps, tool_calls, trace_id, "max_steps"),
                          request, steps, tool_calls, trace_id)

    # ---------- validation ----------
    @staticmethod
    def _validate_decision(decision: Any) -> None:
        if not isinstance(decision, dict):
            raise RejectedAction("DECISION_INVALID", "模型输出不是 JSON 对象")
        action = decision.get("action")
        if not isinstance(action, str) or not action:
            raise RejectedAction("DECISION_INVALID", "模型输出缺少 action")
        args = decision.get("args", {})
        if not isinstance(args, dict):
            raise RejectedAction("DECISION_INVALID", "模型输出的 args 不是对象")
        if action == Action.FINISH and not isinstance(args.get("status"), str):
            raise RejectedAction("DECISION_INVALID", "finish 缺少 status")

    def _validate_finish(self, ctx: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
        """用真实工具状态校验模型给出的结束结论；不一致则强制改为 ERROR。"""
        status = str(args.get("status"))
        review = str(args.get("review_status", ""))
        reason = str(args.get("reason", ""))
        pending = list(args.get("pending") or [])

        material = ctx.get("material")
        material_ready = material is not None and not material.get("missing_fields")
        rules_checked = ctx.get("risks") is not None
        high = [r for r in (ctx.get("risks") or []) if r.get("severity") == "high"]
        slot_checked = ctx.get("slot_info") is not None
        has_proposed = ctx.get("proposed") is not None
        draft = ctx.get("draft_result") or {}
        draft_saved = bool(draft.get("saved"))
        save_error = ctx.get("save_error") is not None
        has_validation_errors = bool(ctx["request"].validation_errors)

        violations: List[str] = []
        if status not in (Status.NEEDS_CONFIRMATION, Status.NEEDS_INPUT, Status.BLOCKED,
                          Status.SAVE_FAILED, Status.INCOMPLETE, Status.ERROR):
            violations.append(f"未知 status: {status}")

        if status == Status.NEEDS_CONFIRMATION:
            if not draft_saved:
                violations.append("声称完成但没有任何已保存草稿")
            if not rules_checked:
                violations.append("声称完成但没有执行规则检查")
            if high:
                violations.append("存在高风险规则却声称可以排期")
            if not slot_checked:
                violations.append("声称完成但没有查询时段")
        elif status == Status.SAVE_FAILED:
            if draft_saved:
                violations.append("声称保存失败但草稿实际已保存")
        elif status == Status.BLOCKED:
            if not (high or slot_checked):
                violations.append("声称阻断但没有风险或时段证据")
            if high and has_proposed:
                violations.append("存在高风险却已生成建议时段")
        elif status == Status.NEEDS_INPUT:
            if not (has_validation_errors or ctx.get("material_error") or not material_ready
                    or not ctx["request"].publish_time):
                violations.append("声称信息缺失但素材与请求信息完整")
        elif status == Status.INCOMPLETE:
            pass
        elif status == Status.ERROR:
            pass

        if review == ReviewStatus.PASS and not rules_checked:
            violations.append("声称审核通过但没有执行规则检查")
        if review == ReviewStatus.PASS and high:
            violations.append("命中高风险规则却声称审核通过")

        if violations:
            return {
                "status": Status.ERROR,
                "review_status": ReviewStatus.ERROR,
                "reason": "模型结论与工具证据不符：" + "；".join(violations),
                "pending": pending + violations,
                "claim_violations": violations,
            }
        return {
            "status": status,
            "review_status": review or ReviewStatus.ERROR,
            "reason": reason,
            "pending": pending,
            "claim_violations": [],
        }

    # ---------- execution ----------
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
                out = self.toolbox.query_slots(args["date"], args["requested_time"],
                                               material_id=request.material_id)
                ctx["slot_info"] = out
                return {"date": out["date"], "date_exists": out["date_exists"],
                        "requested_free": out["requested"]["free"],
                        "available": out["available"], "candidates": out["candidates"],
                        "earlier_candidates": out["earlier_candidates"]}, None
            if name == Action.SAVE_DRAFT:
                out = self.toolbox.save_draft(
                    material_id=request.material_id,
                    date=args["date"], time=args["time"],
                    requested_time=args["requested_time"], hard=args["hard"],
                )
                ctx["draft_result"] = out
                return {"saved": out["saved"], "draft_id": out["draft_id"], "duplicate": out["duplicate"]}, None
            raise RejectedAction("ACTION_UNKNOWN", f"未知工具动作: {name}")
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
        except (KeyError, TypeError) as exc:
            err = {"code": "TOOL_ARGS_INVALID", "message": f"工具参数缺失或类型错误: {exc}", "tool": name}
            if name == Action.SAVE_DRAFT:
                ctx["save_error"] = err
            else:
                ctx["tool_error"] = err
            return {"error": err}, err
        except Exception as exc:  # noqa: BLE001 - 工具内部异常也要转结构化
            err = {"code": "TOOL_INTERNAL", "message": f"工具内部异常: {exc}", "tool": name}
            if name == Action.SAVE_DRAFT:
                ctx["save_error"] = err
            else:
                ctx["tool_error"] = err
            return {"error": err}, err

    # ---------- result assembly ----------
    @staticmethod
    def _safe_decision(decision: Any) -> Dict[str, Any]:
        if isinstance(decision, dict):
            return {"action": str(decision.get("action", "")), "args": decision.get("args", {}),
                    "decision_basis": str(decision.get("decision_basis", ""))}
        return {"action": "invalid", "args": {}, "decision_basis": "模型输出非对象"}

    def _error_result(self, request: Request, ctx: Dict[str, Any], steps: List[Dict[str, Any]],
                      tool_calls: int, trace_id: str, reason: str,
                      violations: List[Dict[str, Any]]) -> Dict[str, Any]:
        args = {"status": Status.ERROR, "review_status": ReviewStatus.ERROR, "reason": reason,
                "pending": [v["message"] for v in violations]}
        result = self._result(request, ctx, args, steps, tool_calls, trace_id)
        result["violations"] = violations
        return result

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
            "evidence": {
                "rules_checked": ctx.get("risks") is not None,
                "slot_checked": ctx.get("slot_info") is not None,
                "draft_saved": bool((ctx.get("draft_result") or {}).get("saved")),
            },
            "claim_violations": args.get("claim_violations", []),
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

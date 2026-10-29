"""离线 Mock 策略模型。

说明：这是"模型决策"的离线替身，用固定规则模拟模型的下一步选择，
只用于验证流程与边界；真实模型走 src/llm/openai_policy.py，动作协议一致。
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from .schemas import Action, ReviewStatus, Status


class MockPolicy:
    name = "mock-policy"

    def __init__(self, search_days: int = 3):
        self.search_days = search_days

    def decide(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        req = ctx["request"]

        # 1) 读取素材
        if ctx.get("material") is None and ctx.get("material_error") is None:
            return self._tool(Action.GET_MATERIAL, {"material_id": req.material_id},
                              "先读取素材元数据，确认存在性与完整性")
        if ctx.get("material_error"):
            return self._finish(Status.NEEDS_INPUT, ReviewStatus.NEEDS_INPUT,
                                "素材不存在或不可读，无法排期",
                                pending=["请核对素材 ID 或补充素材入库"])
        if ctx.get("tool_error"):
            err = ctx["tool_error"]
            return self._finish(Status.ERROR, ReviewStatus.ERROR,
                                f"工具 {err.get('tool')} 执行失败：{err.get('message')}",
                                pending=["工具异常，任务未完成；未生成草稿"])

        mat = ctx["material"]
        if mat["missing_fields"]:
            return self._finish(Status.NEEDS_INPUT, ReviewStatus.NEEDS_INPUT,
                                "素材元数据缺失，无法完成审核",
                                pending=[f"补充必填字段: {', '.join(mat['missing_fields'])}"])

        if not req.publish_date or not req.publish_time:
            return self._finish(Status.NEEDS_INPUT, ReviewStatus.NEEDS_INPUT,
                                "缺少发布日期或时间，无法形成排期草稿",
                                pending=["补充 publish_date / publish_time"])

        # 2) 规则检查
        if ctx.get("risks") is None:
            return self._tool(Action.CHECK_RULES, {"material_id": req.material_id},
                              "素材元数据完整，先做规则风险检查")
        risks = ctx["risks"]
        high = [r for r in risks if r["severity"] == "high"]
        if high:
            return self._finish(Status.BLOCKED, ReviewStatus.RISK_BLOCKED,
                                "命中高风险规则，禁止进入排期",
                                pending=[f"{r['rule_id']}: {r['reason']}" for r in high])

        # 3) 时段查询
        if ctx.get("slot_info") is None:
            return self._tool(Action.QUERY_SLOTS,
                              {"date": req.publish_date, "requested_time": req.publish_time},
                              "规则检查通过，查询用户要求日期/时段的占用情况")
        slot_info = ctx["slot_info"]

        proposed = ctx.get("proposed")
        if proposed is None:
            if slot_info["requested"]["free"]:
                proposed = {"date": slot_info["date"], "time": req.publish_time, "alternative": False}
                ctx["proposed"] = proposed
            else:
                candidates = slot_info["candidates"]
                if candidates:
                    proposed = {"date": slot_info["date"], "time": candidates[0], "alternative": True}
                    ctx["proposed"] = proposed
                else:
                    # 当天无可用时段，继续向后查，最多 search_days 天
                    tried = ctx.setdefault("dates_tried", [req.publish_date])
                    if len(tried) < self.search_days:
                        next_date = self._add_days(req.publish_date, len(tried))
                        tried.append(next_date)
                        return self._tool(
                            Action.QUERY_SLOTS,
                            {"date": next_date, "requested_time": req.publish_time},
                            "当天无可用时段，改用相邻日期继续检索",
                        )
                    return self._finish(
                        Status.BLOCKED, ReviewStatus.NO_SLOT,
                        f"{self.search_days} 天搜索窗口内没有可用时段",
                        pending=["需人工调整发布日期或开放新时段"],
                    )

        # 4) 保存草稿（只存草稿，不发布）
        if ctx.get("draft_result") is None:
            if ctx.get("save_error"):
                return self._finish(Status.SAVE_FAILED, ReviewStatus.SAVE_FAILED,
                                    "草稿保存失败，未生成任何草稿",
                                    pending=["检查存储权限后重试；本次未保存成功"])
            return self._tool(
                Action.SAVE_DRAFT,
                {"date": proposed["date"], "time": proposed["time"], "requested_time": req.publish_time,
                 "hard": req.hard},
                "时段可用，保存排期草稿（待人工确认，不发布）",
            )

        if ctx.get("save_error"):
            return self._finish(Status.SAVE_FAILED, ReviewStatus.SAVE_FAILED,
                                "草稿保存失败，未生成任何草稿",
                                pending=["检查存储权限后重试；本次未保存成功"])

        # 5) 结束：草稿已保存，等待确认
        pending = []
        if proposed["alternative"]:
            pending.append(f"替代时段 {proposed['date']} {proposed['time']} 需用户确认；原要求 {req.publish_time} 未被修改")
        for r in risks:
            if r.get("needs_confirmation"):
                pending.append(f"{r['rule_id']}: {r['reason']}")
        pending.append("草稿需人工确认后才可发布")
        return self._finish(Status.NEEDS_CONFIRMATION, ReviewStatus.PASS,
                            "草稿已保存，等待用户确认", pending=pending)

    # ---------- helpers ----------
    @staticmethod
    def _tool(name: str, args: Dict[str, Any], basis: str) -> Dict[str, Any]:
        return {"action": name, "args": args, "decision_basis": basis}

    @staticmethod
    def _finish(status: str, review_status: str, reason: str, pending=None) -> Dict[str, Any]:
        return {
            "action": Action.FINISH,
            "args": {"status": status, "review_status": review_status, "reason": reason,
                     "pending": pending or []},
            "decision_basis": reason,
        }

    @staticmethod
    def _add_days(date: str, days: int) -> str:
        return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")

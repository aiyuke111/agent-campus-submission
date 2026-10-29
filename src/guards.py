"""边界守卫：禁止发布、动作前置条件、参数不可篡改。

守卫不只检查"动作名是否合法"，还检查"当前上下文是否允许该动作"，
防止模型跳过审核直接保存、或改写用户硬性要求。
"""

from typing import Any, Dict

from .errors import RejectedAction, ToolError
from .schemas import Action, Request


def assert_action_allowed(action_name: str) -> None:
    if action_name in Action.FORBIDDEN:
        raise RejectedAction("ACTION_FORBIDDEN", f"越权动作被拦截: {action_name}")
    if action_name not in Action.TOOLS and action_name != Action.FINISH:
        raise RejectedAction("ACTION_UNKNOWN", f"未知动作: {action_name}")


def assert_request(request: Request) -> None:
    if request.validation_errors:
        raise ToolError("REQUEST_INVALID", "；".join(request.validation_errors))


def hard_requirement_changed(request: Request, proposed_time: str) -> bool:
    if not request.hard:
        return False
    return proposed_time != request.publish_time


def check_preconditions(action: str, args: Dict[str, Any], ctx: Dict[str, Any],
                        request: Request) -> None:
    """在真正执行工具前，校验业务前置条件。"""
    material = ctx.get("material")
    material_ready = material is not None and not material.get("missing_fields")
    risks = ctx.get("risks")
    high = [r for r in (risks or []) if r.get("severity") == "high"]
    slot_info = ctx.get("slot_info")
    proposed = ctx.get("proposed")

    if action == Action.CHECK_RULES:
        if material is None:
            raise RejectedAction("PRECONDITION_MATERIAL", "未读取素材就执行规则检查")
        return

    if action == Action.QUERY_SLOTS:
        if material is None:
            raise RejectedAction("PRECONDITION_MATERIAL", "未读取素材就查询时段")
        if risks is None:
            raise RejectedAction("PRECONDITION_RULES", "未做规则检查就查询时段")
        if high:
            raise RejectedAction("PRECONDITION_RISK", "存在高风险规则，不应继续查询时段")
        return

    if action == Action.SAVE_DRAFT:
        if not material_ready:
            raise RejectedAction("PRECONDITION_MATERIAL", "素材信息不完整，不能保存草稿")
        if risks is None:
            raise RejectedAction("PRECONDITION_RULES", "未做规则检查就保存草稿")
        if high:
            raise RejectedAction("PRECONDITION_RISK", "存在高风险规则，禁止保存草稿")
        if slot_info is None:
            raise RejectedAction("PRECONDITION_SLOTS", "未查询时段就保存草稿")
        if proposed is None:
            raise RejectedAction("PRECONDITION_PROPOSAL", "没有确认建议时段就保存草稿")
        if args.get("date") != proposed["date"] or args.get("time") != proposed["time"]:
            raise RejectedAction("ARGUMENT_TAMPERED", "保存时段与已确认的建议时段不一致")
        if args.get("requested_time") != request.publish_time:
            raise RejectedAction("ARGUMENT_TAMPERED", "requested_time 被改写")
        if bool(args.get("hard")) != bool(request.hard):
            raise RejectedAction("ARGUMENT_TAMPERED", "hard 标志被改写")
        if args.get("time") not in slot_info.get("available", []):
            raise RejectedAction("SLOT_NOT_AVAILABLE", "目标时段当前不可用")
        return


def denied_actions() -> tuple:
    return Action.FORBIDDEN

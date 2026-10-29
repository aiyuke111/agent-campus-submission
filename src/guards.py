"""边界守卫：禁止发布、硬性要求只读、请求合法性校验。"""

from .errors import ToolError
from .schemas import Action, Request


def assert_action_allowed(action_name: str) -> None:
    """本项目只保存草稿，任何发布类动作都视为越权。"""
    if action_name in Action.FORBIDDEN:
        raise RuntimeError(f"越权动作被拦截: {action_name}")
    if action_name not in Action.TOOLS and action_name != Action.FINISH:
        raise RuntimeError(f"未知动作: {action_name}")


def assert_request(request: Request) -> None:
    if not request.material_id:
        raise ToolError("REQUEST_INVALID", "缺少 material_id，无法读取素材")


def hard_requirement_changed(request: Request, proposed_time: str) -> bool:
    """用户的硬性发布时间是否被改动（仅用于标记，不用于静默改值）。"""
    if not request.hard:
        return False
    return proposed_time != request.publish_time


def denied_actions() -> tuple:
    return Action.FORBIDDEN

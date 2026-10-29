"""数据结构与状态枚举。

所有状态都集中在这里定义，避免在业务代码里写裸字符串。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


class Status:
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"  # 草稿已保存，等待用户确认
    NEEDS_INPUT = "NEEDS_INPUT"                # 素材/请求信息不完整
    BLOCKED = "BLOCKED"                        # 规则风险或没有可用时段
    SAVE_FAILED = "SAVE_FAILED"                # 草稿保存失败
    INCOMPLETE = "INCOMPLETE"                  # 达到步数/工具调用上限
    ERROR = "ERROR"                            # 工具异常，任务无法继续


class ReviewStatus:
    PASS = "PASS"
    NEEDS_INPUT = "NEEDS_INPUT"
    RISK_BLOCKED = "RISK_BLOCKED"
    NO_SLOT = "NO_SLOT"
    SAVE_FAILED = "SAVE_FAILED"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"


class Action:
    GET_MATERIAL = "get_material"
    CHECK_RULES = "check_rules"
    QUERY_SLOTS = "query_slots"
    SAVE_DRAFT = "save_draft"
    FINISH = "finish"

    TOOLS = (GET_MATERIAL, CHECK_RULES, QUERY_SLOTS, SAVE_DRAFT)
    # 禁止动作：本项目只保存草稿，不接真实发布
    FORBIDDEN = ("publish", "confirm_publish", "schedule_publish")


@dataclass
class Request:
    material_id: str
    publish_date: str
    publish_time: str
    hard: bool = True
    operator: str = "unknown"
    note: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Request":
        return cls(
            material_id=str(data.get("material_id", "")).strip(),
            publish_date=str(data.get("publish_date", "")).strip(),
            publish_time=str(data.get("publish_time", "")).strip(),
            hard=bool(data.get("hard", True)),
            operator=str(data.get("operator", "unknown")),
            note=str(data.get("note", "")),
        )


@dataclass
class Material:
    material_id: str
    title: str
    metadata: Dict[str, Any]
    missing_fields: List[str] = field(default_factory=list)


@dataclass
class Risk:
    rule_id: str
    severity: str  # high / medium / low
    reason: str
    needs_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "reason": self.reason,
            "needs_confirmation": self.needs_confirmation,
        }


@dataclass
class Slot:
    time: str
    capacity: int
    booked: int
    note: str = ""

    @property
    def free(self) -> bool:
        return self.booked < self.capacity

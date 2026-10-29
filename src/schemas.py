"""数据结构、状态枚举与请求校验。"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


class Status:
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    NEEDS_INPUT = "NEEDS_INPUT"
    BLOCKED = "BLOCKED"
    SAVE_FAILED = "SAVE_FAILED"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"


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
    FORBIDDEN = ("publish", "confirm_publish", "schedule_publish")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _parse_bool(raw: Any, errors: List[str], field_name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "false"):
            return low == "true"
    errors.append(f"{field_name} 必须是布尔值（true/false）")
    return True


def _validate_date(value: str, errors: List[str]) -> None:
    if not value:
        errors.append("缺少 publish_date")
        return
    if not _DATE_RE.match(value):
        errors.append("publish_date 格式应为 YYYY-MM-DD")
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        errors.append("publish_date 不是合法日期")


def _validate_time(value: str, errors: List[str]) -> None:
    if not value:
        errors.append("缺少 publish_time")
        return
    if not _TIME_RE.match(value):
        errors.append("publish_time 格式应为 HH:MM（00:00–23:59）")


@dataclass
class Request:
    material_id: str
    publish_date: str
    publish_time: str
    hard: bool = True
    operator: str = "unknown"
    note: str = ""
    validation_errors: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Request":
        errors: List[str] = []
        material_id = str(data.get("material_id", "") or "").strip()
        date = str(data.get("publish_date", "") or "").strip()
        tm = str(data.get("publish_time", "") or "").strip()
        hard = _parse_bool(data.get("hard", True), errors, "hard")

        if not material_id:
            errors.append("缺少 material_id")
        _validate_date(date, errors)
        _validate_time(tm, errors)

        return cls(
            material_id=material_id,
            publish_date=date,
            publish_time=tm,
            hard=hard,
            operator=str(data.get("operator", "unknown")),
            note=str(data.get("note", "")),
            validation_errors=errors,
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

"""本地工具层：素材读取、规则检查、时段查询、草稿保存。

工具全部为确定性本地实现，便于测试；save_draft 支持注入失败用于验收。
"""

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .errors import ToolError
from .schemas import Material, Risk, Slot


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


class Toolbox:
    """四个业务工具的集合。工具失败统一抛 ToolError。"""

    def __init__(
        self,
        data_dir: str,
        store_path: Optional[str] = None,
        inject: Optional[Dict[str, Any]] = None,
        rules_version: str = "2026.11",
        clock: Optional[Callable[[], str]] = None,
    ):
        self.data_dir = data_dir
        self.materials = {m["material_id"]: m for m in _load_json(os.path.join(data_dir, "materials.json"))["materials"]}
        self.rules_cfg = _load_json(os.path.join(data_dir, "rules.json"))
        self.slots_cfg = _load_json(os.path.join(data_dir, "slots.json"))
        self.store_path = store_path or os.path.join(data_dir, "drafts.json")
        self.inject = inject or {}
        self.rules_version = rules_version
        self.clock = clock or (lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        self.drafts: Dict[str, Dict[str, Any]] = self._load_store()

    # ---------- store ----------
    def _load_store(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.store_path):
            with open(self.store_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        return {}

    def _flush_store(self) -> None:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.drafts, f, ensure_ascii=False, indent=2)

    # ---------- tools ----------
    def get_material(self, material_id: str) -> Dict[str, Any]:
        raw = self.materials.get(material_id)
        if raw is None:
            raise ToolError("MATERIAL_NOT_FOUND", f"素材 {material_id} 不存在")
        metadata = dict(raw.get("metadata", {}))
        missing = [
            field
            for field in self.rules_cfg.get("required_metadata", [])
            if field not in metadata or metadata[field] in (None, "")
        ]
        material = Material(
            material_id=material_id,
            title=raw.get("title", ""),
            metadata=metadata,
            missing_fields=missing,
        )
        return {
            "material_id": material.material_id,
            "title": material.title,
            "metadata": material.metadata,
            "missing_fields": material.missing_fields,
        }

    def check_rules(self, material_id: str) -> Dict[str, Any]:
        material = self.get_material(material_id)
        meta = material["metadata"]
        risks: List[Risk] = []
        for rule in self.rules_cfg.get("rules", []):
            field = rule["field"]
            if field not in meta:
                continue
            if self._match(meta[field], rule["op"], rule["value"]):
                risks.append(
                    Risk(
                        rule_id=rule["rule_id"],
                        severity=rule["severity"],
                        reason=rule["reason"],
                        needs_confirmation=bool(rule.get("needs_confirmation", False)),
                    )
                )
        return {"material_id": material_id, "risks": [r.to_dict() for r in risks]}

    @staticmethod
    def _match(actual: Any, op: str, expected: Any) -> bool:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "gt":
            return actual > expected
        if op == "lt":
            return actual < expected
        if op == "in":
            return actual in expected
        if op == "exists":
            return actual is not None
        raise ToolError("RULE_OP_UNSUPPORTED", f"不支持的规则算子: {op}")

    def query_slots(self, date: str, requested_time: str) -> Dict[str, Any]:
        window = self.slots_cfg["window"]
        dates = self.slots_cfg.get("dates", {})
        raw = dates.get(date, [])
        slots = [Slot(t["time"], int(t.get("capacity", 1)), int(t.get("booked", 0)), t.get("note", "")) for t in raw]
        in_window = window[0] <= requested_time <= window[1]
        requested = next((s for s in slots if s.time == requested_time), None)
        return {
            "date": date,
            "date_exists": date in dates,
            "window": window,
            "requested": {
                "time": requested_time,
                "in_window": in_window,
                "free": bool(requested and requested.free and in_window),
                "note": requested.note if requested else "",
            },
            "occupied": [s.time for s in slots if not s.free],
            "available": [s.time for s in slots if s.free],
            "candidates": [s.time for s in slots if s.free and s.time >= requested_time and in_window],
        }

    def idempotency_key(self, material_id: str, date: str, time: str) -> str:
        raw = f"{material_id}|{date}|{time}|{self.rules_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def save_draft(self, material_id: str, date: str, time: str, requested_time: str, hard: bool) -> Dict[str, Any]:
        if self.inject.get("save_fail"):
            raise ToolError("SAVE_FAILED", "草稿存储不可写（注入故障：save_fail）", retryable=False)
        key = self.idempotency_key(material_id, date, time)
        if key in self.drafts:
            existing = self.drafts[key]
            return {
                "saved": True,
                "duplicate": True,
                "draft_id": existing["draft_id"],
                "idempotency_key": key,
            }
        draft_id = "D" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8].upper()
        self.drafts[key] = {
            "draft_id": draft_id,
            "idempotency_key": key,
            "material_id": material_id,
            "date": date,
            "time": time,
            "requested_time": requested_time,
            "hard_requirement": bool(hard),
            "status": "DRAFT_PENDING_CONFIRMATION",
            "created_at": self.clock(),
            "published": False,
        }
        self._flush_store()
        return {
            "saved": True,
            "duplicate": False,
            "draft_id": draft_id,
            "idempotency_key": key,
        }

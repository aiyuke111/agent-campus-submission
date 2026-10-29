"""本地工具层：素材读取、规则检查、时段查询、草稿保存。

关键工程约束：
- 草稿存储读取/写入加文件锁，写入采用临时文件 + 原子替换；
- 保存前重新读取草稿库，检查"查询之后被别人占用"的竞态；
- 真实 I/O 失败统一转成 ToolError(SAVE_FAILED)，且失败时不提交内存状态。
"""

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional

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
        if not os.path.exists(self.store_path):
            return {}
        try:
            with open(self.store_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ToolError("STORE_CORRUPT", f"草稿库不是合法 JSON: {exc}")
        if not isinstance(data, dict):
            raise ToolError("STORE_CORRUPT", "草稿库结构非法（应为对象）")
        return data

    def _write_store_atomic(self, data: Dict[str, Dict[str, Any]]) -> None:
        """临时文件 + os.replace，避免半截 JSON；失败时清理临时文件。"""
        directory = os.path.dirname(self.store_path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = self.store_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.store_path)
        except OSError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise ToolError("SAVE_FAILED", f"草稿写入失败: {exc}", retryable=True)

    @contextmanager
    def _store_lock(self) -> Iterator[None]:
        """跨进程互斥（Windows 用 msvcrt，POSIX 用 fcntl）。"""
        lock_path = self.store_path + ".lock"
        os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
        handle = open(lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

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

    def _draft_reservations(self, material_id: Optional[str] = None) -> Dict[tuple, str]:
        """已保存草稿占用的 (date, time) -> material_id。

        查询时排除"本素材自己的草稿"，否则同一请求重复提交会因为自己占用了上次
        建议的时段而重新排到别处，导致幂等失效。
        """
        reservations = {}
        for draft in self.drafts.values():
            if material_id is not None and draft["material_id"] == material_id:
                continue
            reservations[(draft["date"], draft["time"])] = draft["material_id"]
        return reservations

    def query_slots(self, date: str, requested_time: str,
                    material_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ToolError("INVALID_DATE", f"日期格式非法: {date}")
        # 查询前重新加载草稿库，避免看到过期占用
        self.drafts = self._load_store()
        reservations = self._draft_reservations(material_id)

        window = self.slots_cfg["window"]
        dates = self.slots_cfg.get("dates", {})
        raw = dates.get(date, [])
        slots = [Slot(t["time"], int(t.get("capacity", 1)), int(t.get("booked", 0)), t.get("note", "")) for t in raw]
        in_window = window[0] <= requested_time <= window[1]
        requested = next((s for s in slots if s.time == requested_time), None)
        occupied = [s.time for s in slots if not s.free or (date, s.time) in reservations]
        available = [s.time for s in slots if s.free and (date, s.time) not in reservations]
        return {
            "date": date,
            "date_exists": date in dates,
            "window": window,
            "requested": {
                "time": requested_time,
                "in_window": in_window,
                "free": bool(requested and requested.free and in_window and (date, requested_time) not in reservations),
                "note": requested.note if requested else "",
            },
            "occupied": occupied,
            "occupied_by_draft": [t for (d, t) in reservations if d == date],
            "available": available,
            "candidates": [t for t in available if t >= requested_time and in_window],
            "earlier_candidates": [t for t in available if t < requested_time and in_window],
        }

    def idempotency_key(self, material_id: str, date: str, time: str,
                        requested_time: str, hard: bool) -> str:
        raw = f"{material_id}|{date}|{time}|{requested_time}|{int(bool(hard))}|{self.rules_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def save_draft(self, material_id: str, date: str, time: str,
                   requested_time: str, hard: bool) -> Dict[str, Any]:
        if self.inject.get("save_fail"):
            raise ToolError("SAVE_FAILED", "草稿存储不可写（注入故障：save_fail）", retryable=False)

        key = self.idempotency_key(material_id, date, time, requested_time, hard)
        with self._store_lock():
            # 保存前重新读取，关闭“查询之后被占用”的竞态
            self.drafts = self._load_store()
            if key in self.drafts:
                existing = self.drafts[key]
                return {
                    "saved": True,
                    "duplicate": True,
                    "draft_id": existing["draft_id"],
                    "idempotency_key": key,
                }
            for other_key, draft in self.drafts.items():
                if draft["date"] == date and draft["time"] == time and other_key != key:
                    if draft["material_id"] == material_id:
                        # 同一素材的不同请求意图可以各自保留草稿；时段占用按素材去重
                        continue
                    raise ToolError(
                        "SLOT_TAKEN",
                        f"时段 {date} {time} 已被素材 {draft['material_id']} 的草稿占用",
                        retryable=False,
                    )
            draft_id = "D" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8].upper()
            new_draft = {
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
            updated = dict(self.drafts)
            updated[key] = new_draft
            # 先落盘成功，再提交内存状态
            self._write_store_atomic(updated)
            self.drafts = updated

        return {
            "saved": True,
            "duplicate": False,
            "draft_id": draft_id,
            "idempotency_key": key,
        }

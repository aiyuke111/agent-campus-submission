import pytest

from src.errors import ToolError
from src.tools import Toolbox


def test_get_material_not_found(toolbox):
    with pytest.raises(ToolError) as exc:
        toolbox.get_material("M99")
    assert exc.value.code == "MATERIAL_NOT_FOUND"


def test_missing_metadata_fields(toolbox):
    material = toolbox.get_material("M02")
    assert set(material["missing_fields"]) == {"duration_s", "category"}


def test_rules_high_and_medium(toolbox):
    risks = {r["rule_id"]: r for r in toolbox.check_rules("M03")["risks"]}
    assert risks["R01"]["severity"] == "high"
    assert risks["R04"]["severity"] == "medium"


def test_rules_sensitive_blocked(toolbox):
    risks = {r["rule_id"]: r for r in toolbox.check_rules("M06")["risks"]}
    assert risks["R02"]["severity"] == "high"
    assert risks["R02"]["needs_confirmation"] is True


def test_slots_conflict_returns_candidates(toolbox):
    slot = toolbox.query_slots("2026-11-05", "18:00")
    assert slot["requested"]["free"] is False
    assert slot["occupied"] == ["09:00", "12:00", "18:00", "21:00"]
    assert slot["candidates"] == ["19:00", "20:00"]


def test_slots_full_day_has_no_candidate(toolbox):
    slot = toolbox.query_slots("2026-11-06", "18:00")
    assert slot["candidates"] == []
    assert slot["available"] == []


def test_save_draft_is_idempotent(toolbox):
    first = toolbox.save_draft("M01", "2026-11-05", "19:00", requested_time="18:00", hard=True)
    second = toolbox.save_draft("M01", "2026-11-05", "19:00", requested_time="18:00", hard=True)
    assert first["draft_id"] == second["draft_id"]
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(toolbox.drafts) == 1


def test_save_draft_failure_is_raised(store, toolbox):
    broken = Toolbox(toolbox.data_dir, store_path=store, inject={"save_fail": True})
    with pytest.raises(ToolError) as exc:
        broken.save_draft("M01", "2026-11-05", "19:00", requested_time="18:00", hard=True)
    assert exc.value.code == "SAVE_FAILED"


def test_idempotency_key_is_stable(toolbox):
    key_a = toolbox.idempotency_key("M01", "2026-11-05", "19:00")
    key_b = toolbox.idempotency_key("M01", "2026-11-05", "19:00")
    key_c = toolbox.idempotency_key("M01", "2026-11-05", "20:00")
    assert key_a == key_b
    assert key_a != key_c

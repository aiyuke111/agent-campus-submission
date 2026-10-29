import json


def test_normal_schedule(run):
    result = run("request_M05_normal")["result"]
    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["review_status"] == "PASS"
    assert result["suggested_slot"]["time"] == "20:00"
    assert result["suggested_slot"]["alternative"] is False
    assert result["draft"]["saved"] is True
    assert result["published"] is False


def test_missing_material_info(run):
    result = run("request_M02_missing")["result"]
    assert result["status"] == "NEEDS_INPUT"
    assert result["review_status"] == "NEEDS_INPUT"
    assert result["draft"]["saved"] is False
    assert any("duration_s" in item for item in result["pending_items"])


def test_rule_risk_blocks_schedule(run):
    result = run("request_M03_risk")["result"]
    assert result["review_status"] == "RISK_BLOCKED"
    assert result["draft"]["saved"] is False
    assert any("版权" in reason for reason in result["risk_reasons"])


def test_time_conflict_proposes_alternative(run):
    result = run("request_M01_conflict")["result"]
    assert result["suggested_slot"]["time"] == "19:00"
    assert result["suggested_slot"]["alternative"] is True
    assert result["suggested_slot"]["hard_requirement_modified"] is False
    assert result["requested_slot"]["time"] == "18:00"
    assert result["draft"]["saved"] is True
    assert any("未被修改" in item for item in result["pending_items"])


def test_no_slot_is_blocked(run):
    result = run("request_M04_no_slot")["result"]
    assert result["review_status"] == "NO_SLOT"
    assert result["status"] == "BLOCKED"
    assert result["draft"]["saved"] is False


def test_duplicate_submission_creates_single_draft(run, store):
    first = run("request_M01_conflict")["result"]
    second = run("request_M01_duplicate")["result"]
    assert first["draft"]["draft_id"] == second["draft"]["draft_id"]
    assert second["draft"]["duplicate"] is True
    with open(store, "r", encoding="utf-8") as f:
        drafts = json.load(f)
    assert len(drafts) == 1


def test_save_failure_is_reported(run):
    result = run("request_M05_normal", inject={"save_fail": True})["result"]
    assert result["status"] == "SAVE_FAILED"
    assert result["review_status"] == "SAVE_FAILED"
    assert result["draft"]["saved"] is False
    assert result["draft"]["error"]["code"] == "SAVE_FAILED"

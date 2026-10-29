import json


def test_conflict_path_action_sequence(run):
    out = run("request_M01_conflict")
    actions = [step["action"] for step in out["trace"]["steps"]]
    assert actions == ["get_material", "check_rules", "query_slots", "save_draft", "finish"]

    query_step = next(s for s in out["trace"]["steps"] if s["action"] == "query_slots")
    assert query_step["args"] == {"date": "2026-11-05", "requested_time": "18:00"}
    assert query_step["observation"]["requested_free"] is False
    assert query_step["observation"]["candidates"] == ["19:00", "20:00"]

    save_step = next(s for s in out["trace"]["steps"] if s["action"] == "save_draft")
    assert save_step["args"]["time"] == "19:00"
    assert save_step["args"]["requested_time"] == "18:00"

    assert all(step["decision_basis"] for step in out["trace"]["steps"])


def test_risk_path_stops_before_slot_query(run):
    out = run("request_M03_risk")
    actions = [step["action"] for step in out["trace"]["steps"]]
    assert actions == ["get_material", "check_rules", "finish"]
    assert "save_draft" not in actions
    assert out["result"]["draft"]["saved"] is False


def test_two_paths_differ(run):
    normal_actions = [s["action"] for s in run("request_M05_normal")["trace"]["steps"]]
    blocked_actions = [s["action"] for s in run("request_M03_risk")["trace"]["steps"]]
    assert normal_actions != blocked_actions


def test_trace_contains_next_action(run):
    steps = run("request_M01_conflict")["trace"]["steps"]
    assert steps[0]["next_action"] == "check_rules"
    assert steps[-1]["next_action"] == "end"


def test_no_publish_action_in_any_trace(run):
    for name in ("request_M01_conflict", "request_M03_risk", "request_M05_normal"):
        for step in run(name)["trace"]["steps"]:
            assert step["action"] not in ("publish", "confirm_publish", "schedule_publish")


def test_trace_has_limits_and_tool_calls(run):
    trace = run("request_M01_conflict")["trace"]
    assert trace["limits"] == {"max_steps": 8, "max_tool_calls": 12}
    assert trace["tool_calls_used"] == 4
    assert trace["policy"] == "mock-policy"

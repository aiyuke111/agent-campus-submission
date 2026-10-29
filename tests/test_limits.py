def test_max_steps_returns_incomplete(run):
    out = run("request_M01_conflict", max_steps=2)
    result = out["result"]
    assert result["status"] == "INCOMPLETE"
    assert result["review_status"] == "INCOMPLETE"
    assert result["collected"]["material"]["material_id"] == "M01"
    assert out["trace"]["steps"][-1]["next_action"] == "end"


def test_max_tool_calls_returns_incomplete(run):
    out = run("request_M01_conflict", max_tool_calls=2)
    result = out["result"]
    assert result["status"] == "INCOMPLETE"
    assert result["tool_calls_used"] == 2
    assert result["draft"]["saved"] is False

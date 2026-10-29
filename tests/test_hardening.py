"""反例/加固测试：覆盖评审指出的 P0/P1 缺陷。"""

import json
import os

import pytest

from helpers import DATA_DIR, build_agent, load_request
from src.errors import PolicyError, ToolError
from src.llm.openai_policy import OpenAIPolicy
from src.schemas import Request
from src.tools import Toolbox


class ScriptedPolicy:
    """按队列返回动作，用于模拟"不守规矩"的模型。"""

    name = "scripted"

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def decide(self, ctx):
        self.calls += 1
        if not self._decisions:
            return {"action": "finish", "args": {"status": "INCOMPLETE", "review_status": "INCOMPLETE",
                                                 "reason": "script exhausted", "pending": []},
                    "decision_basis": "exhausted"}
        return self._decisions.pop(0)


def _finish(status="NEEDS_CONFIRMATION", review="PASS", reason="done"):
    return {"action": "finish", "args": {"status": status, "review_status": review,
                                         "reason": reason, "pending": []}, "decision_basis": "scripted"}


# ---------- 结束结论校验 ----------
def test_finish_cannot_claim_saved_without_draft(store):
    policy = ScriptedPolicy([_finish("NEEDS_CONFIRMATION", "PASS", "已保存")])
    result = build_agent(store, policy=policy).run(load_request("request_M05_normal"))["result"]
    assert result["status"] == "ERROR"
    assert result["draft"]["saved"] is False
    assert result["claim_violations"]


def test_finish_cannot_claim_pass_without_rules(store):
    agent = build_agent(store)
    req = load_request("request_M05_normal")
    ctx = {"request": req, "material": {"missing_fields": []}, "risks": None,
           "slot_info": {"available": ["20:00"]}, "proposed": {"date": req.publish_date,
                                                               "time": "20:00", "alternative": False},
           "draft_result": {"saved": True}, "save_error": None}
    out = agent._validate_finish(ctx, {"status": "NEEDS_CONFIRMATION", "review_status": "PASS",
                                       "reason": "ok", "pending": []})
    assert out["status"] == "ERROR"
    assert any("规则检查" in v for v in out["claim_violations"])


def test_finish_cannot_claim_save_failed_when_saved(store):
    agent = build_agent(store)
    req = load_request("request_M05_normal")
    ctx = {"request": req, "material": {"missing_fields": []}, "risks": [],
           "slot_info": {"available": ["20:00"]}, "proposed": {"date": req.publish_date,
                                                               "time": "20:00", "alternative": False},
           "draft_result": {"saved": True}, "save_error": None}
    out = agent._validate_finish(ctx, {"status": "SAVE_FAILED", "review_status": "SAVE_FAILED",
                                       "reason": "fail", "pending": []})
    assert out["status"] == "ERROR"


# ---------- 跳过审核直接保存 ----------
def test_save_before_audit_is_rejected(store):
    policy = ScriptedPolicy([{
        "action": "save_draft",
        "args": {"date": "2026-11-05", "time": "19:00", "requested_time": "18:00", "hard": True},
        "decision_basis": "直接保存",
    }])
    out = build_agent(store, policy=policy).run(load_request("request_M01_conflict"))
    result = out["result"]
    assert result["status"] == "ERROR"
    assert result["violations"][0]["code"] == "PRECONDITION_MATERIAL"
    assert result["draft"]["saved"] is False
    assert not os.path.exists(store)


def test_high_risk_material_cannot_be_saved(store):
    policy = ScriptedPolicy([
        {"action": "get_material", "args": {"material_id": "M03"}, "decision_basis": "read"},
        {"action": "check_rules", "args": {"material_id": "M03"}, "decision_basis": "rules"},
        {"action": "query_slots", "args": {"date": "2026-11-05", "requested_time": "19:00"},
         "decision_basis": "query"},
    ])
    out = build_agent(store, policy=policy).run(load_request("request_M03_risk"))
    assert out["result"]["status"] == "ERROR"
    assert out["result"]["violations"][0]["code"] == "PRECONDITION_RISK"


# ---------- 模型输出异常 ----------
def test_policy_exception_is_structured(store):
    class BoomPolicy:
        name = "boom"

        def decide(self, ctx):
            raise TimeoutError("model timeout")

    out = build_agent(store, policy=BoomPolicy()).run(load_request("request_M05_normal"))
    assert out["result"]["status"] == "ERROR"
    assert out["result"]["violations"][0]["code"] == "POLICY_ERROR"


def test_policy_non_dict_output_is_structured(store):
    class BadPolicy:
        name = "bad"

        def decide(self, ctx):
            return "not a dict"

    out = build_agent(store, policy=BadPolicy()).run(load_request("request_M05_normal"))
    assert out["result"]["status"] == "ERROR"
    assert out["result"]["violations"][0]["code"] == "DECISION_INVALID"


def test_publish_action_is_rejected(store):
    policy = ScriptedPolicy([{"action": "publish", "args": {}, "decision_basis": "publish"}])
    out = build_agent(store, policy=policy).run(load_request("request_M05_normal"))
    assert out["result"]["status"] == "ERROR"
    assert out["result"]["violations"][0]["code"] == "ACTION_FORBIDDEN"


# ---------- 草稿之间时段冲突 ----------
def test_save_rejects_slot_taken_by_other_material(store):
    tb1 = Toolbox(DATA_DIR, store_path=store)
    tb1.save_draft("M01", "2026-11-05", "19:00", "18:00", True)
    tb2 = Toolbox(DATA_DIR, store_path=store)
    with pytest.raises(ToolError) as exc:
        tb2.save_draft("M05", "2026-11-05", "19:00", "19:00", True)
    assert exc.value.code == "SLOT_TAKEN"


def test_query_sees_saved_drafts(store):
    tb = Toolbox(DATA_DIR, store_path=store)
    tb.save_draft("M01", "2026-11-05", "19:00", "18:00", True)
    slot = Toolbox(DATA_DIR, store_path=store).query_slots("2026-11-05", "18:00")
    assert "19:00" in slot["occupied"]
    assert "19:00" not in slot["available"]
    assert slot["candidates"] == ["20:00"]


def test_agent_avoids_slot_taken_by_other_draft(store):
    build_agent(store).run(load_request("request_M01_conflict"))
    req = Request.from_dict({"material_id": "M05", "publish_date": "2026-11-05",
                             "publish_time": "19:00", "hard": True})
    result = build_agent(store).run(req)["result"]
    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["suggested_slot"]["time"] == "20:00"
    drafts = json.load(open(store, encoding="utf-8"))
    slots = [(d["material_id"], d["time"]) for d in drafts.values()]
    assert len(slots) == len(set(slots))


# ---------- 真实 I/O 失败 ----------
def test_atomic_write_failure_is_tool_error(store, monkeypatch):
    toolbox = Toolbox(DATA_DIR, store_path=store)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(ToolError) as exc:
        toolbox.save_draft("M05", "2026-11-05", "20:00", "20:00", True)
    assert exc.value.code == "SAVE_FAILED"
    assert toolbox.drafts == {}
    # 内存未提交，重试仍失败而不是误判 duplicate
    with pytest.raises(ToolError):
        toolbox.save_draft("M05", "2026-11-05", "20:00", "20:00", True)


def test_agent_real_io_failure_returns_save_failed(store, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    result = build_agent(store).run(load_request("request_M05_normal"))["result"]
    assert result["status"] == "SAVE_FAILED"
    assert result["draft"]["saved"] is False


def test_policy_retries_once_after_slot_taken():
    from src.policy import MockPolicy
    req = load_request("request_M01_conflict")
    policy = MockPolicy(search_days=3)
    ctx = {
        "request": req,
        "material": {"missing_fields": []},
        "risks": [],
        "slot_info": {"date": "2026-11-05", "requested": {"free": False}, "available": ["19:00"],
                      "candidates": ["19:00"], "earlier_candidates": []},
        "proposed": {"date": "2026-11-05", "time": "19:00", "alternative": True},
        "draft_result": None,
        "save_error": {"code": "SLOT_TAKEN", "message": "taken"},
    }
    decision = policy.decide(ctx)
    assert decision["action"] == "query_slots"
    assert ctx["proposed"] is None
    assert ctx["save_error"] is None
    assert ctx["retried_slot_conflict"] is True

    # 重新查询后拿到新时段，应再次尝试保存（只重试一次）
    ctx["slot_info"] = {"date": "2026-11-05", "requested": {"free": False}, "available": ["20:00"],
                        "candidates": ["20:00"], "earlier_candidates": []}
    decision = policy.decide(ctx)
    assert decision["action"] == "save_draft"
    assert decision["args"]["time"] == "20:00"

    # 第二次仍冲突：不再重试，返回失败
    ctx["draft_result"] = None
    ctx["save_error"] = {"code": "SLOT_TAKEN", "message": "taken again"}
    decision = policy.decide(ctx)
    assert decision["action"] == "finish"
    assert decision["args"]["status"] == "SAVE_FAILED"


def test_finish_normalizes_unknown_review_status(store):
    agent = build_agent(store)
    req = load_request("request_M05_normal")
    ctx = {"request": req, "material": {"missing_fields": []}, "risks": [],
           "slot_info": {"available": ["20:00"]}, "proposed": {"date": req.publish_date,
                                                               "time": "20:00", "alternative": False},
           "draft_result": {"saved": True}, "save_error": None}
    out = agent._validate_finish(ctx, {"status": "NEEDS_CONFIRMATION",
                                       "review_status": "PENDING_CONFIRMATION",
                                       "reason": "ok", "pending": []})
    assert out["status"] == "NEEDS_CONFIRMATION"
    assert out["review_status"] == "PASS"
    assert out["normalized"][0]["from"] == "PENDING_CONFIRMATION"


def test_repeated_identical_tool_call_is_rejected(store):
    policy = ScriptedPolicy([
        {"action": "get_material", "args": {"material_id": "M05"}, "decision_basis": "read"},
        {"action": "check_rules", "args": {"material_id": "M05"}, "decision_basis": "rules"},
        {"action": "check_rules", "args": {"material_id": "M05"}, "decision_basis": "rules again"},
    ])
    out = build_agent(store, policy=policy).run(load_request("request_M05_normal"))
    assert out["result"]["status"] == "ERROR"
    assert out["result"]["violations"][0]["code"] == "REPEATED_ACTION"


# ---------- 输入校验 ----------
@pytest.mark.parametrize("payload", [
    {"material_id": "M04", "publish_date": "2026-13-40", "publish_time": "18:00", "hard": True},
    {"material_id": "M01", "publish_date": "2026-11-05", "publish_time": "25:99", "hard": True},
    {"material_id": "M05", "publish_date": "2026-11-05", "publish_time": "20:00", "hard": "maybe"},
    {"material_id": "", "publish_date": "2026-11-05", "publish_time": "20:00", "hard": True},
])
def test_invalid_request_returns_needs_input(store, payload):
    req = Request.from_dict(payload)
    result = build_agent(store).run(req)["result"]
    assert result["status"] == "NEEDS_INPUT"
    assert result["draft"]["saved"] is False


def test_hard_string_false_is_parsed(store):
    req = Request.from_dict({"material_id": "M05", "publish_date": "2026-11-05",
                             "publish_time": "20:00", "hard": "false"})
    assert req.hard is False
    result = build_agent(store).run(req)["result"]
    assert result["requested_slot"]["hard"] is False
    assert result["status"] == "NEEDS_CONFIRMATION"


# ---------- 幂等键包含请求意图 ----------
def test_idempotency_key_includes_requested_intent(store):
    tb = Toolbox(DATA_DIR, store_path=store)
    k1 = tb.idempotency_key("M01", "2026-11-05", "19:00", "18:00", True)
    k2 = tb.idempotency_key("M01", "2026-11-05", "19:00", "17:00", True)
    k3 = tb.idempotency_key("M01", "2026-11-05", "19:00", "18:00", False)
    assert k1 != k2 and k1 != k3


# ---------- search_days 配置生效 ----------
def test_policy_uses_search_days_from_config(store):
    from src.policy import MockPolicy
    out2 = build_agent(store + ".2", policy=MockPolicy(search_days=2)).run(load_request("request_M04_no_slot"))
    out3 = build_agent(store + ".3", policy=MockPolicy(search_days=3)).run(load_request("request_M04_no_slot"))
    q2 = sum(1 for s in out2["trace"]["steps"] if s["action"] == "query_slots")
    q3 = sum(1 for s in out3["trace"]["steps"] if s["action"] == "query_slots")
    assert q2 == 2 and q3 == 3


# ---------- 真实模型适配器异常处理 ----------
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content=None, exc=None):
        self.content = content
        self.exc = exc

    def create(self, **kwargs):
        if self.exc:
            raise self.exc
        return _Resp(self.content)


class _Chat:
    def __init__(self, content=None, exc=None):
        self.completions = _Completions(content, exc)


class FakeClient:
    def __init__(self, content=None, exc=None):
        self.chat = _Chat(content, exc)


def _ctx():
    return {"request": Request("M01", "2026-11-05", "18:00")}


def test_openai_policy_parses_valid_json():
    policy = OpenAIPolicy(client=FakeClient(content=json.dumps(
        {"action": "get_material", "args": {"material_id": "M01"}, "decision_basis": "read"})))
    decision = policy.decide(_ctx())
    assert decision["action"] == "get_material"


def test_openai_policy_rejects_bad_json():
    policy = OpenAIPolicy(client=FakeClient(content="not json"))
    with pytest.raises(PolicyError) as exc:
        policy.decide(_ctx())
    assert exc.value.code == "MODEL_BAD_JSON"


def test_openai_policy_rejects_empty_response():
    policy = OpenAIPolicy(client=FakeClient(content=None))
    with pytest.raises(PolicyError) as exc:
        policy.decide(_ctx())
    assert exc.value.code == "MODEL_RESPONSE_INVALID"


def test_openai_policy_rejects_unknown_action():
    policy = OpenAIPolicy(client=FakeClient(content=json.dumps({"action": "publish", "args": {}})))
    with pytest.raises(PolicyError) as exc:
        policy.decide(_ctx())
    assert exc.value.code == "MODEL_BAD_ACTION"


def test_openai_policy_wraps_client_exception():
    policy = OpenAIPolicy(client=FakeClient(exc=RuntimeError("network down")))
    with pytest.raises(PolicyError) as exc:
        policy.decide(_ctx())
    assert exc.value.code == "MODEL_CALL_FAILED"

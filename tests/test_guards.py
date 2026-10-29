import pytest

from src import guards
from src.errors import RejectedAction
from src.schemas import Request
from src.tools import Toolbox


def test_publish_actions_are_blocked():
    for name in ("publish", "confirm_publish", "schedule_publish"):
        with pytest.raises(RejectedAction) as exc:
            guards.assert_action_allowed(name)
        assert exc.value.code == "ACTION_FORBIDDEN"


def test_unknown_action_is_blocked():
    with pytest.raises(RejectedAction) as exc:
        guards.assert_action_allowed("delete_everything")
    assert exc.value.code == "ACTION_UNKNOWN"


def test_hard_requirement_change_flag():
    req = Request("M01", "2026-11-05", "18:00", hard=True)
    assert guards.hard_requirement_changed(req, "19:00") is True
    assert guards.hard_requirement_changed(req, "18:00") is False
    soft = Request("M01", "2026-11-05", "18:00", hard=False)
    assert guards.hard_requirement_changed(soft, "19:00") is False


def test_toolbox_has_no_publish_capability():
    assert not hasattr(Toolbox, "publish")
    assert not hasattr(Toolbox, "schedule_publish")


def test_precondition_blocks_save_without_material():
    ctx = {"material": None, "risks": None, "slot_info": None, "proposed": None}
    req = Request("M01", "2026-11-05", "18:00")
    with pytest.raises(RejectedAction) as exc:
        guards.check_preconditions("save_draft", {}, ctx, req)
    assert exc.value.code == "PRECONDITION_MATERIAL"


def test_precondition_blocks_save_without_rules():
    ctx = {"material": {"missing_fields": []}, "risks": None, "slot_info": None, "proposed": None}
    req = Request("M01", "2026-11-05", "18:00")
    with pytest.raises(RejectedAction) as exc:
        guards.check_preconditions("save_draft", {}, ctx, req)
    assert exc.value.code == "PRECONDITION_RULES"


def test_precondition_blocks_argument_tampering():
    ctx = {
        "material": {"missing_fields": []},
        "risks": [],
        "slot_info": {"available": ["19:00"]},
        "proposed": {"date": "2026-11-05", "time": "19:00", "alternative": True},
    }
    req = Request("M01", "2026-11-05", "18:00", hard=True)
    args = {"date": "2026-11-05", "time": "19:00", "requested_time": "17:00", "hard": True}
    with pytest.raises(RejectedAction) as exc:
        guards.check_preconditions("save_draft", args, ctx, req)
    assert exc.value.code == "ARGUMENT_TAMPERED"

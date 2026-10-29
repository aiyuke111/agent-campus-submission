import pytest

from src import guards
from src.schemas import Request
from src.tools import Toolbox


def test_publish_actions_are_blocked():
    for name in ("publish", "confirm_publish", "schedule_publish"):
        with pytest.raises(RuntimeError):
            guards.assert_action_allowed(name)


def test_unknown_action_is_blocked():
    with pytest.raises(RuntimeError):
        guards.assert_action_allowed("delete_everything")


def test_hard_requirement_change_flag():
    req = Request("M01", "2026-11-05", "18:00", hard=True)
    assert guards.hard_requirement_changed(req, "19:00") is True
    assert guards.hard_requirement_changed(req, "18:00") is False
    soft = Request("M01", "2026-11-05", "18:00", hard=False)
    assert guards.hard_requirement_changed(soft, "19:00") is False


def test_toolbox_has_no_publish_capability():
    assert not hasattr(Toolbox, "publish")
    assert not hasattr(Toolbox, "schedule_publish")

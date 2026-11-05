import json

import pytest

from bookforge.constants import CHECKPOINTS, LAYER_ORDER
from bookforge.errors import StateError
from bookforge.state import load_state, new_state, save_state


def test_new_state_has_every_layer_and_checkpoint_pending():
    s = new_state("b1")
    assert list(s.layers) == list(LAYER_ORDER)
    assert list(s.checkpoints) == list(CHECKPOINTS)
    assert all(i.status == "pending" and i.version == 0 for i in s.layers.values())
    assert all(c.status == "pending" for c in s.checkpoints.values())


def test_round_trip_and_no_temp_files_left(tmp_path):
    path = tmp_path / "books" / "b1" / "state.json"
    s = new_state("b1")
    s.set_layer_status("synopsis", "drafted", note="first pass")
    save_state(path, s)
    assert load_state(path) == s
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_accepting_bumps_version_only_then():
    s = new_state("b1")
    s.set_layer_status("acts", "drafted")
    assert s.layers["acts"].version == 0
    s.set_layer_status("acts", "accepted")
    s.set_layer_status("acts", "stale")
    s.set_layer_status("acts", "accepted")
    assert s.layers["acts"].version == 2


def test_unknown_layer_or_status_rejected():
    s = new_state("b1")
    with pytest.raises(StateError):
        s.set_layer_status("epilogue", "accepted")
    with pytest.raises(StateError):
        s.set_layer_status("acts", "finished")


def test_checkpoint_lifecycle():
    s = new_state("b1")
    with pytest.raises(StateError, match="not waiting"):
        s.approve_checkpoint("direction")
    s.reach_checkpoint("direction")
    assert s.checkpoints["direction"].status == "waiting"
    s.approve_checkpoint("direction")
    assert s.checkpoints["direction"].status == "approved"
    s.reach_checkpoint("direction")  # reaching again never reopens an approved checkpoint
    assert s.checkpoints["direction"].status == "approved"
    with pytest.raises(StateError):
        s.approve_checkpoint("direction")


def test_unknown_checkpoint_rejected():
    with pytest.raises(StateError, match="unknown checkpoint"):
        new_state("b1").approve_checkpoint("midpoint")


def test_load_errors_are_state_errors(tmp_path):
    with pytest.raises(StateError, match="not found"):
        load_state(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError):
        load_state(broken)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(StateError, match="schema_version"):
        load_state(wrong)
    invalid = tmp_path / "invalid.json"
    data = json.loads(new_state("b1").model_dump_json())
    data["layers"]["acts"]["status"] = "bogus"
    invalid.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateError):
        load_state(invalid)

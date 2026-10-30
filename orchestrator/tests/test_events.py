import json

from orchestrator.engine.events import EventStore, EventType, replay_states
from orchestrator.engine.state import NodeState


def _store(tmp_path):
    store = EventStore(tmp_path / "events.jsonl", "r1")
    store.append(EventType.RUN_STARTED, stages=["a", "b"])
    store.append(EventType.STAGE_STATE, "a", **{"from": "PENDING", "to": "READY"}, reason="")
    store.append(EventType.STAGE_STATE, "a", **{"from": "READY", "to": "RUNNING"}, reason="")
    return store


def test_untouched_log_verifies(tmp_path):
    store = _store(tmp_path)
    ok, msg = EventStore.verify(store.path)
    assert ok, msg


def test_edited_payload_is_detected(tmp_path):
    store = _store(tmp_path)
    lines = store.path.read_text().splitlines()
    event = json.loads(lines[1])
    event["payload"]["to"] = "SUCCEEDED"  # rewrite history
    lines[1] = json.dumps(event)
    store.path.write_text("\n".join(lines) + "\n")
    ok, msg = EventStore.verify(store.path)
    assert not ok and "seq 2" in msg


def test_deleted_event_is_detected(tmp_path):
    store = _store(tmp_path)
    lines = store.path.read_text().splitlines()
    store.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    ok, msg = EventStore.verify(store.path)
    assert not ok


def test_reopened_store_continues_chain(tmp_path):
    _store(tmp_path)
    reopened = EventStore(tmp_path / "events.jsonl", "r1")
    reopened.append(EventType.RUN_COMPLETED, status="FAILED")
    ok, msg = EventStore.verify(reopened.path)
    assert ok, msg
    assert EventStore.load(reopened.path)[-1].seq == 4


def test_replay_rebuilds_state(tmp_path):
    store = _store(tmp_path)
    assert replay_states(EventStore.load(store.path)) == {"a": NodeState.RUNNING, "b": NodeState.PENDING}

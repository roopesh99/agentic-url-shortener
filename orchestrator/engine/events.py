"""Append-only, hash-chained event log.

The event log is the single source of truth for a run: stage states, gate
results, approvals and artifacts are all recorded here, and run state can be
rebuilt from it (`replay_states`). Each event embeds the hash of the previous
one, so any edit, deletion or reordering of the file is detectable (`verify`).
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .state import NodeState

GENESIS_HASH = "0" * 64


class EventType:
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    STAGE_STATE = "STAGE_STATE"
    AGENT_INVOKED = "AGENT_INVOKED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_ERROR = "AGENT_ERROR"
    GATE_RESULT = "GATE_RESULT"
    ARTIFACT_RECORDED = "ARTIFACT_RECORDED"
    DECISION_RECORDED = "DECISION_RECORDED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_DECIDED = "APPROVAL_DECIDED"


class Event(BaseModel):
    run_id: str
    seq: int
    ts: str
    type: str
    stage: str | None = None
    payload: dict[str, Any]
    prev_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        body = self.model_dump(exclude={"hash"})
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


class EventStore:
    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        existing = self.load(path) if path.exists() else []
        self._seq = existing[-1].seq if existing else 0
        self._last_hash = existing[-1].hash if existing else GENESIS_HASH

    def append(self, type_: str, stage: str | None = None, **payload: Any) -> Event:
        with self._lock:
            event = Event(
                run_id=self.run_id,
                seq=self._seq + 1,
                ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                type=type_,
                stage=stage,
                payload=payload,
                prev_hash=self._last_hash,
            )
            event.hash = event.compute_hash()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
            self._seq, self._last_hash = event.seq, event.hash
            return event

    @staticmethod
    def load(path: Path) -> list[Event]:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [Event.model_validate_json(line) for line in lines if line.strip()]

    @staticmethod
    def verify(path: Path) -> tuple[bool, str]:
        """Check the hash chain. Returns (ok, message naming the first bad event)."""
        prev = GENESIS_HASH
        try:
            events = EventStore.load(path)
        except ValueError as exc:
            return False, f"unparseable event log: {exc}"
        for expected_seq, event in enumerate(events, start=1):
            if event.seq != expected_seq:
                return False, f"sequence gap at seq {event.seq} (expected {expected_seq})"
            if event.prev_hash != prev:
                return False, f"chain broken at seq {event.seq}: prev_hash mismatch"
            if event.compute_hash() != event.hash:
                return False, f"tampered event at seq {event.seq}: hash mismatch"
            prev = event.hash
        return True, f"{len(events)} events verified"


def replay_states(events: list[Event]) -> dict[str, NodeState]:
    """Rebuild every stage's current state from the event log alone."""
    states: dict[str, NodeState] = {}
    for e in events:
        if e.type == EventType.RUN_STARTED:
            states.update({s: NodeState.PENDING for s in e.payload.get("stages", [])})
        elif e.type == EventType.STAGE_STATE and e.stage:
            states[e.stage] = NodeState(e.payload["to"])
    return states

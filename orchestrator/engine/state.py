"""Stage node state machine.

Transitions are explicit and enforced: an illegal transition is a bug in the
engine, so it raises rather than silently corrupting run state.
"""

from __future__ import annotations

from enum import Enum


class NodeState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    RETRYING = "RETRYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"   # entry gate not satisfied
    SKIPPED = "SKIPPED"   # an upstream stage did not succeed
    STALE = "STALE"       # an upstream artifact changed after this stage ran


TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.READY, NodeState.SKIPPED}),
    NodeState.READY: frozenset({NodeState.RUNNING, NodeState.BLOCKED, NodeState.SKIPPED}),
    NodeState.RUNNING: frozenset({NodeState.VALIDATING, NodeState.RETRYING, NodeState.FAILED}),
    NodeState.VALIDATING: frozenset(
        {NodeState.SUCCEEDED, NodeState.RETRYING, NodeState.AWAITING_APPROVAL, NodeState.FAILED}
    ),
    NodeState.RETRYING: frozenset({NodeState.RUNNING, NodeState.FAILED}),
    NodeState.AWAITING_APPROVAL: frozenset({NodeState.SUCCEEDED, NodeState.FAILED}),
    NodeState.SUCCEEDED: frozenset({NodeState.STALE}),
    NodeState.FAILED: frozenset({NodeState.ROLLED_BACK}),
    NodeState.ROLLED_BACK: frozenset({NodeState.READY}),
    NodeState.BLOCKED: frozenset({NodeState.READY}),
    NodeState.SKIPPED: frozenset({NodeState.PENDING}),
    NodeState.STALE: frozenset({NodeState.READY, NodeState.PENDING}),
}

TERMINAL: frozenset[NodeState] = frozenset(
    {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.ROLLED_BACK, NodeState.BLOCKED, NodeState.SKIPPED}
)

# States that prevent downstream stages from ever running in this pass.
UNSUCCESSFUL: frozenset[NodeState] = TERMINAL - {NodeState.SUCCEEDED}


class IllegalTransition(RuntimeError):
    pass


def check_transition(current: NodeState, target: NodeState) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")

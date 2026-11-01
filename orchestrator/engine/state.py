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
    # RUNNING -> AWAITING_APPROVAL: policy requires a human before proposed changes are applied
    NodeState.RUNNING: frozenset(
        {NodeState.VALIDATING, NodeState.RETRYING, NodeState.AWAITING_APPROVAL, NodeState.FAILED}
    ),
    NodeState.VALIDATING: frozenset(
        {NodeState.SUCCEEDED, NodeState.RETRYING, NodeState.AWAITING_APPROVAL, NodeState.FAILED}
    ),
    NodeState.RETRYING: frozenset({NodeState.RUNNING, NodeState.FAILED}),
    # AWAITING_APPROVAL -> RETRYING: a human answered open questions; the agent re-runs with the answers
    NodeState.AWAITING_APPROVAL: frozenset(
        {NodeState.VALIDATING, NodeState.SUCCEEDED, NodeState.RETRYING, NodeState.FAILED}
    ),
    NodeState.SUCCEEDED: frozenset({NodeState.STALE}),
    NodeState.FAILED: frozenset({NodeState.ROLLED_BACK}),
    NodeState.ROLLED_BACK: frozenset({NodeState.READY}),
    NodeState.BLOCKED: frozenset({NodeState.READY}),
    NodeState.SKIPPED: frozenset({NodeState.PENDING}),
    # STALE -> SUCCEEDED: re-planning found the stage's inputs unchanged, so its accepted artifact is reused
    NodeState.STALE: frozenset({NodeState.READY, NodeState.PENDING, NodeState.SUCCEEDED}),
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

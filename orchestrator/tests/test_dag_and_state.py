from pathlib import Path

import pytest

from orchestrator.engine.dag import WorkflowError, downstream, load_workflow, topological_order, validate
from orchestrator.engine.models import WorkflowSpec
from orchestrator.engine.state import IllegalTransition, NodeState, check_transition

ROOT = Path(__file__).resolve().parents[2]


def wf(*stages):
    return WorkflowSpec.model_validate({"name": "t", "stages": list(stages)})


def test_skeleton_workflow_loads_and_orders():
    workflow = load_workflow(ROOT / "workflows" / "skeleton.yaml")
    order = topological_order(workflow)
    assert order[0] == "requirements" and order[-1] == "test"
    assert workflow.stage("requirements").approval.value == "required"
    # string gate refs are normalized to GateRef
    assert workflow.stage("requirements").exit_gates[1].name == "ambiguities_resolved"


def test_cycle_is_rejected():
    with pytest.raises(WorkflowError, match="cycle"):
        validate(wf({"id": "a", "agent": "x", "needs": ["b"]}, {"id": "b", "agent": "x", "needs": ["a"]}))


def test_unknown_dependency_is_rejected():
    with pytest.raises(WorkflowError, match="unknown stage"):
        validate(wf({"id": "a", "agent": "x", "needs": ["ghost"]}))


def test_duplicate_ids_are_rejected():
    with pytest.raises(WorkflowError, match="duplicate"):
        validate(wf({"id": "a", "agent": "x"}, {"id": "a", "agent": "y"}))


def test_downstream_is_transitive():
    w = wf(
        {"id": "a", "agent": "x"},
        {"id": "b", "agent": "x", "needs": ["a"]},
        {"id": "c", "agent": "x", "needs": ["b"]},
        {"id": "d", "agent": "x"},
    )
    assert downstream(w, "a") == {"b", "c"}
    assert downstream(w, "d") == set()


def test_retry_attempts_are_bounded():
    with pytest.raises(ValueError):
        wf({"id": "a", "agent": "x", "retry": {"max_attempts": 50}})


@pytest.mark.parametrize(
    "current,target",
    [
        (NodeState.PENDING, NodeState.RUNNING),          # must pass through READY
        (NodeState.RUNNING, NodeState.SUCCEEDED),        # must pass through gates
        (NodeState.AWAITING_APPROVAL, NodeState.RETRYING),
        (NodeState.SUCCEEDED, NodeState.FAILED),
    ],
)
def test_illegal_transitions_raise(current, target):
    with pytest.raises(IllegalTransition):
        check_transition(current, target)


def test_legal_transition_passes():
    check_transition(NodeState.VALIDATING, NodeState.AWAITING_APPROVAL)

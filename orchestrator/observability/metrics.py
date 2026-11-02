"""Reliability metrics computed from a run's event log alone.

The audit log is the single source of truth, so every number here can be recomputed by anyone
holding the (hash-verified) log. Definitions:

- Retries are split by cause. Failure retries (agent error, gate failure, policy rejection) are
  distinct from clarification rounds, reviewer change requests and fallbacks, which are not failures.
- An incident opens at a stage's first failure since its last success (a failure retry, a switch to
  the fallback agent, or FAILED) and closes at that stage's next SUCCEEDED. MTTR is the mean open time; it includes time a run sat
  stopped before a person fixed something and resumed it. Unrecovered incidents are counted apart.
- Latency splits wall-clock time into active work, waiting for humans, and stopped between processes.
- Stage success rate counts executed stages only; a SKIPPED stage never ran and is reported apart.
- Human decisions are counted once: a resume that replays a recorded approval (same artifact hash)
  or recorded answers (same question set) marks them `reused` instead of counting them again.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..engine.events import Event, EventType

ACTIVE_STATES = {"READY", "RUNNING", "VALIDATING", "RETRYING"}
HUMAN_STATES = {"AWAITING_APPROVAL"}


def ts(event: Event) -> datetime:
    return datetime.fromisoformat(event.ts)


def retry_cause(reason: str) -> str:
    if reason.startswith("clarified by"):
        return "clarification"
    if reason.startswith("changes requested"):
        return "change_request"
    if reason.startswith("fallback to agent"):
        return "fallback"
    return "failure"


@dataclass
class Interval:
    stage: str
    state: str
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


@dataclass
class Incident:
    stage: str
    opened: datetime
    reason: str
    closed: datetime | None = None
    failures: int = 1  # failures of the stage while this incident stayed open

    @property
    def seconds(self) -> float | None:
        return (self.closed - self.opened).total_seconds() if self.closed else None


@dataclass
class RunMetrics:
    run_id: str
    workflow: str
    status: str
    processes: int
    started: datetime
    finished: datetime
    wall_seconds: float
    active_seconds: float
    human_wait_seconds: float
    stopped_seconds: float
    stages: dict[str, dict[str, Any]]
    retries: Counter
    rollbacks: int
    rolled_back_stages: int
    incidents: list[Incident]
    gates: dict[str, int]
    policy: Counter
    approvals: list[dict[str, Any]]
    clarifications: list[dict[str, Any]]
    llm: dict[str, Any]
    replans: int
    intervals: list[Interval] = field(default_factory=list)
    selection: dict[str, Any] | None = None  # how `orch run auto` chose the workflow

    @property
    def stage_outcomes(self) -> Counter:
        return Counter(o for s in self.stages.values() for o in s["outcomes"])

    @property
    def stage_success_rate(self) -> float | None:
        """Executed stages that succeeded; SKIPPED stages never ran and are excluded."""
        outcomes = self.stage_outcomes
        executed = sum(n for o, n in outcomes.items() if o != "SKIPPED")
        return outcomes["SUCCEEDED"] / executed if executed else None

    @property
    def human_decisions(self) -> dict[str, int]:
        distinct = lambda items: [i for i in items if not i["reused"]]
        approvals = distinct(self.approvals)
        return {
            "approvals": len(approvals),
            "approved": sum(a["approved"] for a in approvals),
            "rejected": sum(not a["approved"] for a in approvals),
            "change_requests": sum(not a["approved"] and a["with_comment"] for a in approvals),
            "clarification_rounds": len(distinct(self.clarifications)),
            "answers": sum(c["questions"] for c in distinct(self.clarifications)),
            "reused_on_resume": sum(i["reused"] for i in self.approvals + self.clarifications),
        }

    @property
    def mttr_seconds(self) -> float | None:
        closed = [i.seconds for i in self.incidents if i.closed]
        return sum(closed) / len(closed) if closed else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "workflow": self.workflow, "status": self.status, "processes": self.processes,
            "started": self.started.isoformat(), "finished": self.finished.isoformat(),
            "latency_seconds": {"wall": round(self.wall_seconds, 3), "active": round(self.active_seconds, 3),
                                "human_wait": round(self.human_wait_seconds, 3),
                                "stopped": round(self.stopped_seconds, 3)},
            "stage_success_rate": self.stage_success_rate,
            "stage_outcomes": dict(self.stage_outcomes),
            "stages": self.stages,
            "retries": dict(self.retries),
            "rollbacks": {"reverted_change_sets": self.rollbacks, "rolled_back_stages": self.rolled_back_stages},
            "incidents": [{"stage": i.stage, "opened": i.opened.isoformat(), "reason": i.reason,
                           "failures": i.failures, "recovered_after_seconds": i.seconds} for i in self.incidents],
            "human_decisions": self.human_decisions,
            "mttr_seconds": self.mttr_seconds,
            "gates": self.gates, "policy": dict(self.policy),
            "approvals": self.approvals, "clarifications": self.clarifications,
            "llm": self.llm, "replans": self.replans,
        }


def compute(events: list[Event]) -> RunMetrics:
    if not events or events[0].type != EventType.RUN_STARTED:
        raise ValueError("an event log starts with RUN_STARTED")
    start_types = (EventType.RUN_STARTED, EventType.RUN_RESUMED)
    segments: list[tuple[datetime, datetime]] = []
    seg_start: datetime | None = None
    for e in events:
        if e.type in start_types:
            if seg_start is not None:  # a process that ended without RUN_COMPLETED (crash, kill)
                segments.append((seg_start, prev_ts))
            seg_start = ts(e)
        elif e.type == EventType.RUN_COMPLETED and seg_start is not None:
            segments.append((seg_start, ts(e)))
            seg_start = None
        prev_ts = ts(e)
    if seg_start is not None:
        segments.append((seg_start, ts(events[-1])))

    def segment_end(moment: datetime) -> datetime:
        return next((end for begin, end in segments if begin <= moment <= end), ts(events[-1]))

    started, finished = ts(events[0]), ts(events[-1])
    wall = (finished - started).total_seconds()
    running = sum((end - begin).total_seconds() for begin, end in segments)

    # --- per-stage state intervals, outcomes and incidents ----------------------------------------
    transitions: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.type == EventType.STAGE_STATE:
            transitions[e.stage].append(e)

    intervals: list[Interval] = []
    stages: dict[str, dict[str, Any]] = {}
    retries: Counter = Counter()
    incidents: list[Incident] = []
    for stage, changes in transitions.items():
        active = human = 0.0
        outcomes: list[str] = []
        open_incident: Incident | None = None
        for i, change in enumerate(changes):
            state, at = change.payload["to"], ts(change)
            nxt = ts(changes[i + 1]) if i + 1 < len(changes) else None
            end = min(nxt, segment_end(at)) if nxt else segment_end(at)
            if state in ACTIVE_STATES | HUMAN_STATES:
                interval = Interval(stage, state, at, end)
                intervals.append(interval)
                if state in HUMAN_STATES:
                    human += interval.seconds
                else:
                    active += interval.seconds
            reason = change.payload["reason"]
            if state == "RETRYING":
                retries[retry_cause(reason)] += 1
            # Engaging the fallback means the primary agent failed: an incident, recovered by the fallback.
            is_failure = state == "FAILED" or (state == "RETRYING" and retry_cause(reason) in ("failure", "fallback"))
            if is_failure and open_incident is None:
                open_incident = Incident(stage, at, reason)
                incidents.append(open_incident)
            elif state == "FAILED" and open_incident is not None:
                open_incident.failures += 1
            if state == "SUCCEEDED":
                if open_incident is not None:
                    open_incident.closed = at
                    open_incident = None
            if state in ("SUCCEEDED", "FAILED", "ROLLED_BACK", "SKIPPED", "BLOCKED"):
                outcomes.append(state)
        stages[stage] = {"active_seconds": round(active, 3), "human_wait_seconds": round(human, 3),
                         "outcomes": outcomes}

    # Final outcome per stage per process: a FAILED followed by ROLLED_BACK is one outcome.
    for stage, data in stages.items():
        collapsed = []
        for outcome in data["outcomes"]:
            if outcome == "ROLLED_BACK" and collapsed and collapsed[-1] == "FAILED":
                collapsed[-1] = "ROLLED_BACK"
            else:
                collapsed.append(outcome)
        data["outcomes"] = collapsed

    # --- agents, gates, policy, humans, LLM -------------------------------------------------------
    attempts: Counter = Counter()
    agent_ms: Counter = Counter()
    gate_ms: Counter = Counter()
    gates = {"passed": 0, "failed": 0}
    policy: Counter = Counter()
    pending_approval: dict[str, Event] = {}
    approvals, clarifications = [], []
    pending_clarification: dict[str, Event] = {}
    llm_calls = []
    seen_decisions: set = set()
    rollbacks = replans = 0
    for e in events:
        p = e.payload
        if e.type == EventType.AGENT_INVOKED:
            attempts[e.stage] += 1
        elif e.type in (EventType.AGENT_COMPLETED, EventType.AGENT_ERROR):
            agent_ms[e.stage] += p.get("duration_ms", 0)
            llm_calls += p.get("llm_calls", [])
        elif e.type == EventType.GATE_RESULT:
            gates["passed" if p["passed"] else "failed"] += 1
            gate_ms[e.stage] += p.get("duration_ms", 0)
        elif e.type == EventType.POLICY_EVALUATED:
            policy[p["tier"]] += 1
        elif e.type == EventType.APPROVAL_REQUESTED:
            pending_approval[e.stage] = e
        elif e.type == EventType.APPROVAL_DECIDED and e.stage in pending_approval:
            req = pending_approval.pop(e.stage)
            key = (e.stage, (p.get("artifact") or {}).get("sha"), req.payload.get("source", "workflow"))
            approvals.append({"stage": e.stage, "source": req.payload.get("source", "workflow"),
                              "reused": key in seen_decisions,
                              "approved": p["approved"], "approver": p["approver"],
                              "with_comment": bool(p.get("comment")),
                              "wait_seconds": round((ts(e) - ts(req)).total_seconds(), 3)})
            seen_decisions.add(key)
        elif e.type == EventType.CLARIFICATION_REQUESTED:
            pending_clarification[e.stage] = e
        elif e.type == EventType.CLARIFICATION_ANSWERED and e.stage in pending_clarification:
            req = pending_clarification.pop(e.stage)
            questions = sorted(q["question"] for q in req.payload["questions"])
            key = (e.stage, hashlib.sha256("\n".join(questions).encode()).hexdigest())
            clarifications.append({"stage": e.stage, "round": p["round"], "questions": len(p["answers"]),
                                   "reused": key in seen_decisions,
                                   "answered_by": p["answered_by"], "source": p["source"],
                                   "wait_seconds": round((ts(e) - ts(req)).total_seconds(), 3)})
            seen_decisions.add(key)
        elif e.type == EventType.CHANGES_REVERTED:
            rollbacks += 1
        elif e.type == EventType.RUN_REPLANNED:
            replans += 1
    for stage in stages:
        stages[stage].update(attempts=attempts[stage], agent_seconds=round(agent_ms[stage] / 1000, 3),
                             gate_seconds=round(gate_ms[stage] / 1000, 3))

    by_source = Counter(c.get("source", "live") for c in llm_calls)
    live = [c for c in llm_calls if c.get("source") == "live"]
    llm = {
        "calls": len(llm_calls), "by_source": dict(by_source),
        "live_input_tokens": sum(c.get("input_tokens", 0) + c.get("cache_read_input_tokens", 0) for c in live),
        "live_output_tokens": sum(c.get("output_tokens", 0) for c in live),
        "live_cost_usd": round(sum(c.get("cost_usd", 0.0) for c in live), 6),
        "unpriced_live_calls": sum(1 for c in live if not c.get("priced", True)),
        "live_call_seconds": round(sum(c.get("duration_ms", 0) for c in live) / 1000, 3),
    }

    human = sum(s["human_wait_seconds"] for s in stages.values())
    completed = [e for e in events if e.type == EventType.RUN_COMPLETED]
    return RunMetrics(
        run_id=events[0].run_id, workflow=events[0].payload.get("workflow", ""),
        selection=events[0].payload.get("selection"),
        status=completed[-1].payload["status"] if completed else "INCOMPLETE",
        processes=sum(1 for e in events if e.type in start_types),
        started=started, finished=finished, wall_seconds=wall,
        active_seconds=max(0.0, running - human_overlap(intervals)), human_wait_seconds=human_overlap(intervals),
        stopped_seconds=max(0.0, wall - running),
        stages=stages, retries=retries, rollbacks=rollbacks,
        rolled_back_stages=sum(s["outcomes"].count("ROLLED_BACK") for s in stages.values()),
        incidents=incidents, gates=gates, policy=policy, approvals=approvals, clarifications=clarifications,
        llm=llm, replans=replans, intervals=intervals,
    )


def human_overlap(intervals: list[Interval]) -> float:
    """Wall-clock seconds during which at least one stage waited for a human (parallel waits count once)."""
    spans = sorted((i.start, i.end) for i in intervals if i.state in HUMAN_STATES)
    total, cur_start, cur_end = 0.0, None, None
    for start, end in spans:
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += (cur_end - cur_start).total_seconds()
    return total


@dataclass
class Portfolio:
    runs: list[RunMetrics]

    def as_dict(self) -> dict[str, Any]:
        closed = [i.seconds for r in self.runs for i in r.incidents if i.closed]
        outcomes = Counter()
        for r in self.runs:
            outcomes.update(r.stage_outcomes)
        executed = sum(n for o, n in outcomes.items() if o != "SKIPPED")
        decisions = Counter()
        for r in self.runs:
            decisions.update(r.human_decisions)
        retries = Counter()
        for r in self.runs:
            retries.update(r.retries)
        return {
            "runs": len(self.runs),
            "run_success_rate": sum(r.status == "SUCCEEDED" for r in self.runs) / len(self.runs) if self.runs else None,
            "stage_success_rate": outcomes["SUCCEEDED"] / executed if executed else None,
            "stage_outcomes": dict(outcomes),
            "human_decisions": dict(decisions),
            "retries": dict(retries),
            "rollbacks": sum(r.rollbacks for r in self.runs),
            "incidents": sum(len(r.incidents) for r in self.runs),
            "unrecovered_incidents": sum(1 for r in self.runs for i in r.incidents if not i.closed),
            "mttr_seconds": sum(closed) / len(closed) if closed else None,
            "active_seconds": round(sum(r.active_seconds for r in self.runs), 3),
            "human_wait_seconds": round(sum(r.human_wait_seconds for r in self.runs), 3),
            "live_llm_calls": sum(r.llm["by_source"].get("live", 0) for r in self.runs),
            "live_output_tokens": sum(r.llm["live_output_tokens"] for r in self.runs),
        }

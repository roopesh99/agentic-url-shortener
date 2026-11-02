"""Markdown run reports: metrics, a timeline, and the human decisions, all from the event log."""

from __future__ import annotations

from datetime import datetime, timedelta

from .metrics import HUMAN_STATES, Portfolio, RunMetrics

METRIC_NOTES = (
    "Computed from the hash-chained event log only (`orch verify-audit` checks it). Retries are split by "
    "cause; clarification rounds and change requests are not failures. An incident opens at a stage's first "
    "failure (including a switch to the fallback agent) and closes at its next success; MTTR includes time a run sat stopped before a person fixed it. "
    "Stage success rate counts executed stages (SKIPPED ones never ran). Human decisions replayed by a "
    "resume are counted once."
)


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    if seconds < 60:
        return f"{seconds:.1f} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def _selection(m: RunMetrics) -> list[str]:
    s = m.selection
    if not s:
        return []
    last = s["proposals"][-1]
    rejected = [d for d in s["decisions"] if not d["approved"]]
    lines = [f"Workflow chosen by `orch run auto`: proposed `{last['workflow']}` ({last['confidence']} confidence, "
             f"by {last['source']}) from {', '.join(f'`{n}`' for n in s['eligible'])}; confirmed by "
             f"{s['decisions'][-1]['approver']}" + (f" after {len(rejected)} rejection(s)" if rejected else "")
             + f". {last['rationale']}", ""]
    return lines


def render_run(m: RunMetrics) -> str:
    h = m.human_decisions
    lines = [
        f"# Run report: `{m.run_id}`",
        "",
        f"Workflow `{m.workflow}` · **{m.status}** · {m.processes} process(es) · "
        f"{m.started:%Y-%m-%d %H:%M} → {m.finished:%Y-%m-%d %H:%M} UTC",
        "",
        *_selection(m),
        "## Reliability",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stage success rate | {percent(m.stage_success_rate)} ({_outcomes(m)}) |",
        f"| Failure retries | {m.retries.get('failure', 0)} |",
        f"| Clarification rounds / change requests / fallbacks | {m.retries.get('clarification', 0)} / "
        f"{m.retries.get('change_request', 0)} / {m.retries.get('fallback', 0)} |",
        f"| Rollbacks (reverted change sets / stages ended ROLLED_BACK) | {m.rollbacks} / {m.rolled_back_stages} |",
        f"| Incidents (unrecovered) | {len(m.incidents)} ({sum(1 for i in m.incidents if not i.closed)}) |",
        f"| MTTR | {duration(m.mttr_seconds)} |",
        f"| Gate checks passed / failed | {m.gates['passed']} / {m.gates['failed']} |",
        f"| Policy evaluations by risk tier | {_tiers(m)} |",
        f"| Re-plans | {m.replans} |",
        "",
        "## Latency",
        "",
        "| | Time |",
        "|---|---|",
        f"| End to end (wall clock) | {duration(m.wall_seconds)} |",
        f"| Active (agents, gates, orchestration) | {duration(m.active_seconds)} |",
        f"| Waiting for humans | {duration(m.human_wait_seconds)} |",
        f"| Stopped between processes | {duration(m.stopped_seconds)} |",
        "",
        "| Stage | Attempts | Active | of which agent | of which gates | Waiting for humans | Outcomes |",
        "|---|---|---|---|---|---|---|",
    ]
    for stage, d in m.stages.items():
        lines.append(f"| `{stage}` | {d['attempts']} | {duration(d['active_seconds'])} | {duration(d['agent_seconds'])} "
                     f"| {duration(d['gate_seconds'])} | {duration(d['human_wait_seconds'])} | {', '.join(d['outcomes'])} |")
    lines += ["", "## Human oversight", "",
              f"{h['approvals']} approval decision(s) ({h['approved']} approved, {h['rejected']} rejected, "
              f"{h['change_requests']} with a change request), {h['clarification_rounds']} clarification round(s) "
              f"answering {h['answers']} question(s); {h['reused_on_resume']} recorded decision(s) reused by resumes.",
              "", "| Kind | Stage | Decision | By | Waited |", "|---|---|---|---|---|"]
    for a in m.approvals:
        if not a["reused"]:
            verdict = "approved" if a["approved"] else ("rejected with change request" if a["with_comment"] else "rejected")
            lines.append(f"| {a['source']} approval | `{a['stage']}` | {verdict} | {a['approver']} | {duration(a['wait_seconds'])} |")
    for c in m.clarifications:
        if not c["reused"]:
            lines.append(f"| clarification round {c['round']} | `{c['stage']}` | {c['questions']} answer(s) | "
                         f"{c['answered_by']} | {duration(c['wait_seconds'])} |")
    if m.incidents:
        lines += ["", "## Incidents", "", "| Stage | Opened | Failures | Recovered after | First failure |", "|---|---|---|---|---|"]
        for i in m.incidents:
            recovered = duration(i.seconds) if i.closed else "not recovered"
            lines.append(f"| `{i.stage}` | {i.opened:%H:%M:%S} | {i.failures} | {recovered} | {i.reason[:110]} |")
    llm = m.llm
    lines += ["", "## LLM usage", "",
              f"{llm['calls']} call(s): " + ", ".join(f"{n} {s}" for s, n in sorted(llm["by_source"].items())) +
              f". Live: {llm['live_input_tokens']:,} input / {llm['live_output_tokens']:,} output tokens, "
              f"{duration(llm['live_call_seconds'])} in calls, cost ${llm['live_cost_usd']:.2f}"
              + (f" ({llm['unpriced_live_calls']} call(s) on an unpriced backend)" if llm["unpriced_live_calls"] else "") + ".",
              "", "## Timeline", "", *_gantt(m), "", "---", "", f"_{METRIC_NOTES}_", ""]
    return "\n".join(lines)


def render_portfolio(portfolio: Portfolio) -> str:
    p = portfolio.as_dict()
    h = p["human_decisions"]
    lines = [
        "# Delivery metrics across runs", "",
        "| Metric | Value |", "|---|---|",
        f"| Runs (succeeded) | {p['runs']} ({percent(p['run_success_rate'])}) |",
        f"| Stage success rate | {percent(p['stage_success_rate'])} |",
        f"| Failure retries | {p['retries'].get('failure', 0)} |",
        f"| Clarification rounds (incl. replays) / change requests | {p['retries'].get('clarification', 0)} / "
        f"{p['retries'].get('change_request', 0)} |",
        f"| Rollbacks | {p['rollbacks']} |",
        f"| Incidents (unrecovered) | {p['incidents']} ({p['unrecovered_incidents']}) |",
        f"| MTTR | {duration(p['mttr_seconds'])} |",
        f"| Human decisions | {h.get('approvals', 0)} approvals ({h.get('rejected', 0)} rejected), "
        f"{h.get('answers', 0)} answers in {h.get('clarification_rounds', 0)} rounds |",
        f"| Active time / waiting for humans | {duration(p['active_seconds'])} / {duration(p['human_wait_seconds'])} |",
        f"| Live LLM calls / output tokens | {p['live_llm_calls']} / {p['live_output_tokens']:,} |",
        "", "| Run | Workflow | Status | Processes | Stage success | Failure retries | Rollbacks | Incidents | MTTR "
        "| Active | Human wait | End to end |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in portfolio.runs:
        lines.append(
            f"| `{m.run_id}` | {m.workflow} | {m.status} | {m.processes} | {percent(m.stage_success_rate)} "
            f"| {m.retries.get('failure', 0)} | {m.rollbacks} | {len(m.incidents)} | {duration(m.mttr_seconds)} "
            f"| {duration(m.active_seconds)} | {duration(m.human_wait_seconds)} | {duration(m.wall_seconds)} |")
    lines += ["", "---", "", f"_{METRIC_NOTES}_", ""]
    return "\n".join(lines)


def _outcomes(m: RunMetrics) -> str:
    return ", ".join(f"{n} {o.lower()}" for o, n in sorted(m.stage_outcomes.items()))


def _tiers(m: RunMetrics) -> str:
    order = ["low", "medium", "high", "critical"]
    return ", ".join(f"{t} {m.policy[t]}" for t in order if m.policy.get(t)) or "–"


def _gantt(m: RunMetrics) -> list[str]:
    """Mermaid Gantt chart: active work and human waits per stage."""
    fmt = "%Y-%m-%dT%H:%M:%S"
    out = ["```mermaid", "gantt", f"    title {m.run_id}", "    dateFormat YYYY-MM-DDTHH:mm:ss",
           "    axisFormat %H:%M"]
    merged: dict[str, list[list]] = {}
    for i in m.intervals:
        kind = "waiting for human" if i.state in HUMAN_STATES else "active"
        spans = merged.setdefault(i.stage, [])
        if spans and spans[-1][0] == kind and (i.start - spans[-1][2]).total_seconds() < 1:
            spans[-1][2] = i.end
        else:
            spans.append([kind, i.start, i.end])
    for stage, spans in merged.items():
        out.append(f"    section {stage}")
        for kind, start, end in spans:
            tag = "crit, " if kind == "waiting for human" else ""
            out.append(f"    {kind} :{tag}{_floor(start).strftime(fmt)}, {_ceil(end, start).strftime(fmt)}")
    out.append("```")
    return out


def _floor(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def _ceil(moment: datetime, start: datetime) -> datetime:
    """Whole seconds, and at least one second long so short spans stay visible."""
    end = moment.replace(microsecond=0) + (timedelta(seconds=1) if moment.microsecond else timedelta())
    return max(end, _floor(start) + timedelta(seconds=1))

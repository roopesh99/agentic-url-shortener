"""Command-line entry point:
`orch run | resume | replan | stop | status | report | verify-audit | pending | approve | answer | respond`."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agents.base import AgentRegistry
from .agents.stubs import stub_agents
from .approvals.service import (AutoApprover, CLIApprover, FileApprover, PresetAnswers, pending_approvals,
                                pending_clarifications, record_answers, record_decision)
from .engine.dag import load_workflow
from .engine.events import EventStore, EventType, replay_states
from .engine.scheduler import STOP_FILE, Engine, ResumeError
from .fileio import is_private, load_env_file, write_atomic
from .gates.builtin import builtin_gates
from .policy.engine import PolicyEngine

DEFAULT_RUNS_DIR = Path("runs")
DEFAULT_POLICY = Path("policies/default.yaml")
DEFAULT_CASSETTES = Path("scenarios/cassettes")


def _new_run_id(workflow_name: str) -> str:
    return f"{workflow_name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"


def _agents(args: argparse.Namespace, workflow_name: str, run_dir: Path) -> AgentRegistry:
    if args.agents == "stub":
        return stub_agents()
    from .agents.llm_agents import LLM_AGENT_NAMES, llm_agents
    from .llm.factory import model_for

    cassettes = Path(args.cassettes) if args.cassettes else DEFAULT_CASSETTES / f"{workflow_name}-{Path(args.requirement).stem}"
    llm, config = _llm(args, cassettes, run_dir, LLM_AGENT_NAMES)
    return llm_agents(llm, lambda agent: model_for(config, agent))


def _llm(args: argparse.Namespace, cassettes: Path, run_dir: Path, agent_names: list[str]):
    from .llm.factory import BackendSpec, LLMConfig, build_llm, describe, load_config
    from .llm.replay import CassetteLLM, Mode

    if args.llm_config:
        config = load_config(Path(args.llm_config))
    else:
        session_agents = [a.strip() for a in (args.session_agents or "").split(",") if a.strip()]
        config = LLMConfig(default=BackendSpec(provider=args.provider, model=args.model),
                           agents={a: BackendSpec(provider="session") for a in session_agents})

    mode = Mode(args.llm)
    if mode is Mode.REPLAY:
        llm = CassetteLLM(cassettes, mode)  # no credentials needed; models still key the cassettes
    else:
        inner = build_llm(config, agent_names, session_dir=run_dir / "llm-requests",
                          require_pricing=args.max_cost_usd is not None)
        llm = inner if mode is Mode.LIVE else CassetteLLM(cassettes, mode, inner)
    print(f"agents: {describe(config, agent_names)}; llm mode={mode.value}"
          + ("" if mode is Mode.LIVE else f", cassettes={cassettes}"))
    return llm, config


def _selection_recordings(args: argparse.Namespace, workspace: Path, selection: dict | None) -> list[str]:
    """The selector's cassette directory, if it lies inside the workspace: written before the run's
    branch exists, it must not make the tree look dirty."""
    if not selection or args.agents != "llm":
        return []
    cassettes = Path(args.cassettes) if args.cassettes else DEFAULT_CASSETTES / f"select-{Path(args.requirement).stem}"
    try:
        return [cassettes.resolve().relative_to(workspace.resolve()).as_posix()]
    except ValueError:
        return []


def _select_workflow(args: argparse.Namespace, run_id: str, run_dir: Path):
    """`orch run auto`: rules decide which workflows are eligible, the selector agent proposes one,
    a person confirms (or rejects with a comment the selector must follow)."""
    from .llm.factory import model_for
    from .planner.select import select

    llm, model = None, ""
    if args.agents == "llm":
        cassettes = Path(args.cassettes) if args.cassettes else DEFAULT_CASSETTES / f"select-{Path(args.requirement).stem}"
        llm, config = _llm(args, cassettes, run_dir, ["selector"])
        model = model_for(config, "selector")
    candidate, record = asyncio.run(select(
        Path(args.requirement).read_text(encoding="utf-8"), Path(args.workspace), Path(args.workflows_dir),
        _approver(args, run_dir), run_id, llm=llm, model=model))
    print(f"[select] {candidate.name}: {record['proposals'][-1]['rationale']}", flush=True)
    return candidate.path, record


def _approver(args: argparse.Namespace, run_dir: Path):
    if args.auto_approve or args.approvals == "auto":
        approver = AutoApprover()
    elif args.approvals == "file":
        approver = FileApprover(run_dir / "approvals")
    else:
        approver = CLIApprover()
    return PresetAnswers(Path(args.answers), approver) if args.answers else approver


# Settings a run is started with, saved to runs/<id>/run.json so `orch resume` rebuilds the same run.
# Paths and choices only: credentials come from the environment, never from here.
RUN_SETTINGS = ("workflow", "requirement", "workspace", "policy", "max_parallel", "agents", "llm", "cassettes",
                "llm_config", "provider", "model", "session_agents", "approvals", "auto_approve", "answers",
                "recorded_decisions", "max_cost_usd", "max_minutes", "git")


def cmd_run(args: argparse.Namespace) -> int:
    auto = args.workflow == "auto"
    workflow = None if auto else load_workflow(Path(args.workflow))
    run_id = args.run_id or _new_run_id(workflow.name if workflow else "auto")
    run_dir = Path(args.runs_dir) / run_id
    if (run_dir / "events.jsonl").exists():
        print(f"run '{run_id}' already exists at {run_dir}", file=sys.stderr)
        return 2
    # Default: an isolated workspace inside the run. Pointing at a real repository is explicit.
    args.workspace = str(Path(args.workspace).resolve() if args.workspace else (run_dir / "workspace").resolve())
    for name in ("workflow", "requirement", "policy", "cassettes", "llm_config", "answers"):
        if getattr(args, name):
            setattr(args, name, str(Path(getattr(args, name)).resolve()))
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.recorded_decisions:
        _seed_decisions(Path(args.recorded_decisions), run_dir / "approvals")
        args.recorded_decisions = str(Path(args.recorded_decisions).resolve())
        args.approvals, args.auto_approve = "file", False
    selection = None
    if auto:
        from .planner.select import SelectionRejected

        try:
            path, selection = _select_workflow(args, run_id, run_dir)
        except SelectionRejected as exc:
            print(f"error: {exc}; no run was started", file=sys.stderr)
            return 1
        args.workflow = str(Path(path).resolve())
        workflow = load_workflow(Path(args.workflow))
    write_atomic(run_dir / "run.json", json.dumps({k: getattr(args, k) for k in RUN_SETTINGS}, indent=2))
    return _execute(args, workflow, run_id, run_dir, resume=False, selection=selection)


def _seed_decisions(source: Path, approvals: Path) -> None:
    """Replay recorded human decisions. Their ids are content hashes (artifact or question set), so a
    decision only ever applies to the exact content it was made on; anything else waits for a person."""
    if not source.is_dir():
        raise FileNotFoundError(f"no recorded decisions directory {source}")
    approvals.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for path in sorted(source.glob("*.decision.json")) + sorted(source.glob("*.answered.json")):
        write_atomic(approvals / path.name, path.read_text(encoding="utf-8"))
        seeded += 1
    print(f"seeded {seeded} recorded human decision(s) from {source}", flush=True)


def cmd_resume(args: argparse.Namespace, replan_from: list[str] | None = None, replan_reason: str = "") -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    settings_path = run_dir / "run.json"
    if not settings_path.exists():
        print(f"error: {settings_path} not found (runs started before resume support cannot be resumed)",
              file=sys.stderr)
        return 2
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    if getattr(args, "approvals", None):
        saved["approvals"], saved["auto_approve"] = args.approvals, False
    if getattr(args, "requirement", None):
        # The new requirement becomes the run's requirement from now on; the engine sees its hash change.
        saved["requirement"] = str(Path(args.requirement).resolve())
        write_atomic(settings_path, json.dumps(saved, indent=2))
    resumed = argparse.Namespace(**saved, runs_dir=args.runs_dir, run_id=args.run_id)
    try:
        return _execute(resumed, load_workflow(Path(resumed.workflow)), args.run_id, run_dir, resume=True,
                        replan_from=replan_from, replan_reason=replan_reason)
    except ResumeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def cmd_replan(args: argparse.Namespace) -> int:
    """Invalidate stages (and everything downstream) of a finished or stopped run and continue it.
    Downstream stages whose inputs turn out unchanged are reused, not re-run."""
    if not args.from_stage and not args.requirement:
        print("error: give --from <stage> and/or --requirement <file>", file=sys.stderr)
        return 2
    return cmd_resume(args, replan_from=args.from_stage, replan_reason=args.reason)


def cmd_eval_selector(args: argparse.Namespace) -> int:
    """Run the workflow selector on cases whose correct workflow is known; exit 1 on any miss."""
    import tempfile

    from .llm.factory import model_for
    from .planner.eval import evaluate, render

    args.max_cost_usd, args.provider, args.model, args.session_agents = None, "anthropic", None, None
    with tempfile.TemporaryDirectory() as tmp:
        llm, config = _llm(args, Path(args.cassettes), Path(tmp), ["selector"])
        results = asyncio.run(evaluate(Path(args.cases), Path(args.workflows_dir), llm, model_for(config, "selector")))
    print(render(results))
    return 0 if all(r["correct"] for r in results) else 1


def cmd_stop(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    if not (run_dir / "events.jsonl").exists():
        print(f"error: no run '{args.run_id}' in {args.runs_dir}", file=sys.stderr)
        return 2
    write_atomic(run_dir / STOP_FILE, f"stop requested by {getpass.getuser()}\n")
    print(f"{args.run_id}: stop requested. No new work starts; in-flight steps finish. Continue with: "
          f"orch resume {args.run_id}")
    return 0


def _execute(args: argparse.Namespace, workflow, run_id: str, run_dir: Path, *, resume: bool,
             replan_from: list[str] | None = None, replan_reason: str = "", selection: dict | None = None) -> int:
    from .workspace.git import GitWorkspace

    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    engine = Engine(
        workflow,
        _agents(args, workflow.name, run_dir),
        builtin_gates(),
        _approver(args, run_dir),
        policy=PolicyEngine.load(Path(args.policy)),
        run_id=run_id,
        run_dir=run_dir,
        workspace=workspace,
        requirement=Path(args.requirement).read_text(encoding="utf-8"),
        max_parallel=args.max_parallel,
        max_cost_usd=args.max_cost_usd,
        max_minutes=args.max_minutes,
        git=GitWorkspace(workspace, run_id, untracked_ok=_selection_recordings(args, workspace, selection))
        if args.git else None,
        selection=selection,
    )
    print(f"{'resuming' if resume else 'run'} {run_id}: workflow={workflow.name} workspace={workspace}", flush=True)
    result = asyncio.run(engine.run(resume=resume, replan_from=replan_from, replan_reason=replan_reason))
    _print_states(result.states)
    status = "SUCCEEDED" if result.succeeded else ("HALTED" if engine._halt_reason else "FAILED")
    print(f"\n{status} in {result.duration_ms / 1000:.1f}s, LLM cost ${engine.cost_usd:.2f}")
    if engine._halt_reason:
        print(f"halted: {engine._halt_reason}. Continue with: orch resume {run_id}")
    print(f"audit log: {run_dir / 'events.jsonl'}")
    return 0 if result.succeeded else 1


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.runs_dir) / args.run_id / "events.jsonl"
    events = EventStore.load(path)
    _print_states(replay_states(events))  # state comes from the event log alone
    print()
    for e in events:
        if e.type == EventType.STAGE_STATE:
            print(f"{e.ts}  {e.stage:<14} {e.payload['from']:>17} -> {e.payload['to']:<17} {e.payload['reason']}")
        elif e.type == EventType.POLICY_EVALUATED:
            print(f"{e.ts}  {e.stage:<14} policy: {e.payload['action']} ({e.payload['tier']} risk, "
                  f"{len(e.payload['violations'])} violation(s), {len(e.payload['files'])} file(s))")
            for v in e.payload["violations"]:
                print(f"{'':<46}- [{v['rule']}] {v['path'] or ''}{':' + str(v['line']) if v['line'] else ''} {v['message']}")
        elif e.type == EventType.APPROVAL_DECIDED:
            verdict = "APPROVED" if e.payload["approved"] else "REJECTED"
            print(f"{e.ts}  {e.stage:<14} {verdict} by {e.payload['approver']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .observability.metrics import Portfolio, compute
    from .observability.report import render_portfolio, render_run

    runs_dir = Path(args.runs_dir)
    if args.all:
        logs = sorted(runs_dir.glob("*/events.jsonl"))
        if not logs:
            print(f"error: no runs in {runs_dir}", file=sys.stderr)
            return 2
        portfolio = Portfolio([compute(EventStore.load(path)) for path in logs])
        text = json.dumps(portfolio.as_dict(), indent=2, default=str) if args.json else render_portfolio(portfolio)
    else:
        if not args.run_id:
            print("error: give a run id or --all", file=sys.stderr)
            return 2
        path = runs_dir / args.run_id / "events.jsonl"
        ok, message = EventStore.verify(path)
        if not ok:
            print(f"error: refusing to report on an unverifiable log ({message})", file=sys.stderr)
            return 2
        metrics = compute(EventStore.load(path))
        text = json.dumps(metrics.as_dict(), indent=2, default=str) if args.json else render_run(metrics)
    if args.out:
        write_atomic(Path(args.out), text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_verify_audit(args: argparse.Namespace) -> int:
    ok, message = EventStore.verify(Path(args.runs_dir) / args.run_id / "events.jsonl")
    print(("OK: " if ok else "TAMPERED: ") + message)
    return 0 if ok else 1


def cmd_pending(args: argparse.Namespace) -> int:
    directory = Path(args.runs_dir) / args.run_id / "approvals"
    items = pending_approvals(directory)
    questions = pending_clarifications(directory)
    if not items and not questions:
        print("nothing pending")
    for clarify_id, req in questions:
        print(f"\n[{clarify_id}] stage={req.stage}: {len(req.questions)} question(s) need your answer")
        for i, q in enumerate(req.questions, start=1):
            print(f"  {i}. {q['question']}\n     why: {q.get('why', '')}")
        print(f"  fill in : {directory / f'{clarify_id}.answers.yaml'}\n"
              f"  submit  : orch answer {args.run_id} {clarify_id}")
    for approval_id, req in items:
        print(f"\n[{approval_id}] stage={req.stage}\n  reason : {req.reason}\n  summary: {req.summary}")
        for label, values in (("decisions", req.decisions), ("evidence", req.gate_evidence),
                              ("files", req.files_changed)):
            if values:
                print(f"  {label}:")
                print("\n".join(f"    - {v}" for v in values))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    decision = record_decision(Path(args.runs_dir) / args.run_id / "approvals", args.approval_id,
                               approved=not args.reject, comment=args.comment)
    print(f"{args.approval_id}: {'APPROVED' if decision.approved else 'REJECTED'} by {decision.approver}")
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    response = record_answers(Path(args.runs_dir) / args.run_id / "approvals", args.clarify_id,
                              Path(args.answers_file) if args.answers_file else None)
    print(f"{args.clarify_id}: {len(response.answers)} answer(s) recorded by {response.answered_by}")
    return 0


def cmd_respond(args: argparse.Namespace) -> int:
    """Answer a session request: raw JSON, or files from a directory packaged as a code change."""
    req_path = Path(args.request)
    request = json.loads(req_path.read_text(encoding="utf-8"))
    if args.json:
        data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    else:
        root = Path(args.files_from)
        files = [{"path": p.relative_to(root).as_posix(), "content": p.read_text(encoding="utf-8")}
                 for p in sorted(root.rglob("*")) if p.is_file()]
        decisions = [dict(zip(("topic", "choice", "rationale"), d.split("::", 2))) for d in args.decision]
        data = {"summary": args.summary, "files": files, "decisions": decisions}
    missing = [k for k in request["schema"].get("required", []) if k not in data]
    if missing:
        print(f"response is missing required keys: {missing}", file=sys.stderr)
        return 2
    resp_path = req_path.with_name(req_path.name.replace(".request.json", ".response.json"))
    write_atomic(resp_path, json.dumps(data, indent=2))
    print(f"wrote {resp_path} ({len(data.get('files', []))} file(s))")
    return 0


def _print_states(states) -> None:
    for stage, state in states.items():
        print(f"  {stage:<14} {state.value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orch", description="Governed agentic SDLC orchestrator")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--env-file", default=".env",
                        help="KEY=value file loaded at startup (default: .env); existing variables win")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="execute a workflow")
    run.add_argument("workflow", help="workflow YAML, or 'auto' to have one proposed from the requirement "
                                      "and confirmed by a person")
    run.add_argument("--workflows-dir", default="workflows", help="where 'auto' looks for workflows")
    run.add_argument("--requirement", required=True, help="requirement markdown file")
    run.add_argument("--workspace", help="directory agents write into (default: runs/<run-id>/workspace). "
                                          "An existing git repository is used only on a new orch/<run-id> branch")
    run.add_argument("--run-id")
    run.add_argument("--policy", default=str(DEFAULT_POLICY), help="governance policy YAML")
    run.add_argument("--max-parallel", type=int, default=4)
    run.add_argument("--agents", choices=["stub", "llm"], default="stub",
                     help="deterministic stubs, or Claude-backed agents")
    run.add_argument("--llm", choices=["live", "record", "rerecord", "replay"], default="replay",
                     help="live: call the API; record: reuse saved cassettes and record missing ones; "
                          "rerecord: call the API for everything; replay: saved cassettes only (offline)")
    run.add_argument("--cassettes", help="cassette directory (default: scenarios/cassettes/<workflow>-<requirement>)")
    run.add_argument("--llm-config", help="YAML mapping agents to backends (see config/); overrides "
                                           "--provider/--model/--session-agents")
    run.add_argument("--provider", default="anthropic", help="default backend: anthropic | openai | session")
    run.add_argument("--model", help="default backend's model (anthropic defaults to claude-opus-5-5)")
    run.add_argument("--session-agents", help="comma-separated agents served by an assistant session "
                                               "through files instead of the API (e.g. coder,tester)")
    run.add_argument("--approvals", choices=["cli", "file", "auto"], default="cli",
                     help="cli: prompt in this terminal; file: persisted, decided with `orch approve`; "
                          "auto: non-human (recorded as such)")
    run.add_argument("--auto-approve", action="store_true", help="same as --approvals auto")
    run.add_argument("--answers", help="reviewed answers file for open questions (deterministic replays); "
                                       "questions it does not cover go to the approver")
    run.add_argument("--recorded-decisions", help="replay the human decisions recorded in a run's approvals/ "
                                                  "directory (implies --approvals file; content-bound, so they "
                                                  "only apply to identical content)")
    run.add_argument("--max-cost-usd", type=float, help="safe-stop the run once LLM spend reaches this")
    run.add_argument("--max-minutes", type=float, help="safe-stop the run after this much wall-clock time")
    run.add_argument("--no-git", dest="git", action="store_false",
                     help="skip git checkpoints (one commit per accepted stage) in the workspace")
    run.set_defaults(func=cmd_run)

    resume = sub.add_parser("resume", help="continue a stopped, halted or failed run from its event log")
    resume.add_argument("run_id")
    resume.add_argument("--approvals", choices=["cli", "file", "auto"], help="override the saved approval mode")
    resume.set_defaults(func=cmd_resume)

    replan = sub.add_parser("replan", help="re-plan a run after an upstream change: invalidate stages and "
                                           "continue, reusing downstream outputs whose inputs are unchanged")
    replan.add_argument("run_id")
    replan.add_argument("--from", dest="from_stage", action="append", default=[],
                        help="stage to re-run, with everything downstream of it (repeatable)")
    replan.add_argument("--requirement", help="a revised requirement file; the run continues from it")
    replan.add_argument("--reason", default="", help="why, for the audit log")
    replan.add_argument("--approvals", choices=["cli", "file", "auto"], help="override the saved approval mode")
    replan.set_defaults(func=cmd_replan)

    stop = sub.add_parser("stop", help="safe-stop a running run (it can be resumed)")
    stop.add_argument("run_id")
    stop.set_defaults(func=cmd_stop)

    pending = sub.add_parser("pending", help="list approvals awaiting a decision")
    pending.add_argument("run_id")
    pending.set_defaults(func=cmd_pending)

    approve = sub.add_parser("approve", help="record your approval decision (identity: your OS user)")
    approve.add_argument("run_id")
    approve.add_argument("approval_id")
    approve.add_argument("--reject", action="store_true")
    approve.add_argument("--comment", default="")
    approve.set_defaults(func=cmd_approve)

    answer = sub.add_parser("answer", help="submit your answers to a stage's open questions")
    answer.add_argument("run_id")
    answer.add_argument("clarify_id")
    answer.add_argument("--from", dest="answers_file",
                        help="answers YAML to use instead of the run's generated <clarify_id>.answers.yaml")
    answer.set_defaults(func=cmd_answer)

    respond = sub.add_parser("respond", help="answer a session-served agent request")
    respond.add_argument("request", help="path to <agent>-<key>.request.json")
    src = respond.add_mutually_exclusive_group(required=True)
    src.add_argument("--json", help="response JSON file")
    src.add_argument("--files-from", help="directory whose files (paths relative to it) form a code change")
    respond.add_argument("--summary", default="")
    respond.add_argument("--decision", action="append", default=[], help="topic::choice::rationale (repeatable)")
    respond.set_defaults(func=cmd_respond)

    ev = sub.add_parser("eval-selector", help="check workflow selection against cases with known answers")
    ev.add_argument("--cases", default="scenarios/selection/eval.yaml")
    ev.add_argument("--workflows-dir", default="workflows")
    ev.add_argument("--llm", choices=["live", "record", "rerecord", "replay"], default="replay")
    ev.add_argument("--llm-config", required=True, help="YAML mapping agents to backends (the selector's backend)")
    ev.add_argument("--cassettes", default=str(DEFAULT_CASSETTES / "selector-eval"))
    ev.set_defaults(func=cmd_eval_selector)

    status = sub.add_parser("status", help="rebuild run state from its event log")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    report = sub.add_parser("report", help="reliability metrics, latency, human decisions and timeline for a run")
    report.add_argument("run_id", nargs="?")
    report.add_argument("--all", action="store_true", help="aggregate every run in --runs-dir")
    report.add_argument("--json", action="store_true", help="machine-readable metrics instead of markdown")
    report.add_argument("--out", help="write to this file instead of stdout")
    report.set_defaults(func=cmd_report)

    verify = sub.add_parser("verify-audit", help="verify the event log hash chain")
    verify.add_argument("run_id")
    verify.set_defaults(func=cmd_verify_audit)

    args = parser.parse_args(argv)
    env_file = Path(args.env_file)
    try:
        loaded = load_env_file(env_file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if loaded:
        # names only: values (keys) are never printed
        print(f"loaded {env_file}: {', '.join(loaded)}", file=sys.stderr)
        if not is_private(env_file):
            print(f"warning: {env_file} is readable by other users; run: chmod 600 {env_file}", file=sys.stderr)
    from .engine.dag import WorkflowError
    from .llm.factory import ConfigError
    from .policy.engine import PolicyConfigError
    try:
        return args.func(args)
    except (ConfigError, WorkflowError, PolicyConfigError, FileNotFoundError, FileExistsError, ValueError,
            ResumeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

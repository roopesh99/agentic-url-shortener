"""Command-line entry point: `orch run | status | verify-audit | pending | approve | answer | respond`."""

from __future__ import annotations

import argparse
import asyncio
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
from .engine.scheduler import Engine
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
    from .llm.factory import BackendSpec, LLMConfig, build_llm, describe, load_config, model_for
    from .llm.replay import CassetteLLM, Mode

    if args.llm_config:
        config = load_config(Path(args.llm_config))
    else:
        session_agents = [a.strip() for a in (args.session_agents or "").split(",") if a.strip()]
        config = LLMConfig(default=BackendSpec(provider=args.provider, model=args.model),
                           agents={a: BackendSpec(provider="session") for a in session_agents})

    mode = Mode(args.llm)
    cassettes = Path(args.cassettes) if args.cassettes else DEFAULT_CASSETTES / f"{workflow_name}-{Path(args.requirement).stem}"
    if mode is Mode.REPLAY:
        llm = CassetteLLM(cassettes, mode)  # no credentials needed; models still key the cassettes
    else:
        inner = build_llm(config, LLM_AGENT_NAMES, session_dir=run_dir / "llm-requests",
                          require_pricing=args.max_cost_usd is not None)
        llm = inner if mode is Mode.LIVE else CassetteLLM(cassettes, mode, inner)
    print(f"agents: {describe(config, LLM_AGENT_NAMES)}; llm mode={mode.value}"
          + ("" if mode is Mode.LIVE else f", cassettes={cassettes}"))
    return llm_agents(llm, lambda agent: model_for(config, agent))


def _approver(args: argparse.Namespace, run_dir: Path):
    if args.auto_approve or args.approvals == "auto":
        approver = AutoApprover()
    elif args.approvals == "file":
        approver = FileApprover(run_dir / "approvals")
    else:
        approver = CLIApprover()
    return PresetAnswers(Path(args.answers), approver) if args.answers else approver


def cmd_run(args: argparse.Namespace) -> int:
    workflow = load_workflow(Path(args.workflow))
    run_id = args.run_id or _new_run_id(workflow.name)
    run_dir = Path(args.runs_dir) / run_id
    if (run_dir / "events.jsonl").exists():
        print(f"run '{run_id}' already exists at {run_dir}", file=sys.stderr)
        return 2
    workspace = Path(args.workspace).resolve()
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
    )
    print(f"run {run_id}: workflow={workflow.name} workspace={workspace}", flush=True)
    result = asyncio.run(engine.run())
    _print_states(result.states)
    print(f"\n{'SUCCEEDED' if result.succeeded else 'FAILED'} in {result.duration_ms / 1000:.1f}s, "
          f"LLM cost ${engine.cost_usd:.2f}")
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
    run.add_argument("workflow", help="workflow YAML")
    run.add_argument("--requirement", required=True, help="requirement markdown file")
    run.add_argument("--workspace", default=".", help="directory agents write into")
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
    run.add_argument("--max-cost-usd", type=float, help="safe-stop the run once LLM spend reaches this")
    run.set_defaults(func=cmd_run)

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

    status = sub.add_parser("status", help="rebuild run state from its event log")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

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
    except (ConfigError, WorkflowError, PolicyConfigError, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

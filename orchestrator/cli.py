"""Command-line entry point: `orch run | status | verify-audit`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agents.stubs import stub_agents
from .approvals.service import AutoApprover, CLIApprover
from .engine.dag import load_workflow
from .engine.events import EventStore, EventType, replay_states
from .engine.scheduler import Engine
from .gates.builtin import builtin_gates
from .policy.engine import PolicyEngine

DEFAULT_RUNS_DIR = Path("runs")
DEFAULT_POLICY = Path("policies/default.yaml")


def _new_run_id(workflow_name: str) -> str:
    return f"{workflow_name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"


def cmd_run(args: argparse.Namespace) -> int:
    workflow = load_workflow(Path(args.workflow))
    run_id = args.run_id or _new_run_id(workflow.name)
    run_dir = Path(args.runs_dir) / run_id
    if (run_dir / "events.jsonl").exists():
        print(f"run '{run_id}' already exists at {run_dir}", file=sys.stderr)
        return 2
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    approver = AutoApprover() if args.auto_approve else CLIApprover()

    engine = Engine(
        workflow,
        stub_agents(),
        builtin_gates(),
        approver,
        policy=PolicyEngine.load(Path(args.policy)),
        run_id=run_id,
        run_dir=run_dir,
        workspace=workspace,
        requirement=Path(args.requirement).read_text(encoding="utf-8"),
        max_parallel=args.max_parallel,
    )
    print(f"run {run_id}: workflow={workflow.name} workspace={workspace}")
    result = asyncio.run(engine.run())
    _print_states(result.states)
    print(f"\n{'SUCCEEDED' if result.succeeded else 'FAILED'} in {result.duration_ms / 1000:.1f}s")
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


def _print_states(states) -> None:
    for stage, state in states.items():
        print(f"  {stage:<14} {state.value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orch", description="Governed agentic SDLC orchestrator")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="execute a workflow")
    run.add_argument("workflow", help="workflow YAML")
    run.add_argument("--requirement", required=True, help="requirement markdown file")
    run.add_argument("--workspace", default=".", help="directory agents write into")
    run.add_argument("--run-id")
    run.add_argument("--policy", default=str(DEFAULT_POLICY), help="governance policy YAML")
    run.add_argument("--max-parallel", type=int, default=4)
    run.add_argument("--auto-approve", action="store_true",
                     help="non-interactive approvals (recorded as non-human in the audit log)")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="rebuild run state from its event log")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    verify = sub.add_parser("verify-audit", help="verify the event log hash chain")
    verify.add_argument("run_id")
    verify.set_defaults(func=cmd_verify_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

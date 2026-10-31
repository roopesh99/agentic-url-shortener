"""Human checkpoints: approvals and clarifications.

An `Approver` is asked to decide on a stage's output (approve/reject) and to
answer open questions a gate raised (clarify). The CLI approver prompts a human;
`FileApprover` persists requests for unattended runs; `AutoApprover` exists for
CI and tests and records itself as the approver so the audit log never pretends
a human signed off. Non-human approvers never answer product questions.
"""

from __future__ import annotations

import asyncio
import getpass
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ..fileio import write_atomic


class ApprovalRequest(BaseModel):
    run_id: str
    stage: str
    reason: str                      # why approval is required
    summary: str                     # agent's summary of its output
    gate_evidence: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    artifact_sha: str = ""           # the exact content being approved


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str
    comment: str = ""


class ClarificationRequest(BaseModel):
    run_id: str
    stage: str
    round: int
    questions: list[dict[str, str]]  # {"question", "why"}


def _clarify_id(request: "ClarificationRequest") -> str:
    """Bound to the exact questions: a resumed run asking the same questions finds the answers
    already given; different questions get a new checkpoint."""
    digest = hashlib.sha256("\n".join(sorted(q["question"] for q in request.questions)).encode()).hexdigest()
    return f"{request.stage}-clarify-{request.round}-{digest[:6]}"


class ClarificationResponse(BaseModel):
    answers: list[dict[str, str]]    # {"question", "answer"}
    answered_by: str
    source: str = "human"            # human | answers-file

    def missing(self, request: ClarificationRequest) -> list[str]:
        given = {a["question"]: a.get("answer", "").strip() for a in self.answers}
        return [q["question"] for q in request.questions if not given.get(q["question"])]


class Approver(ABC):
    @abstractmethod
    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...

    async def clarify(self, request: ClarificationRequest) -> ClarificationResponse | None:
        """Answer open questions, or None when this approver cannot (the stage then fails)."""
        return None


class AutoApprover(Approver):
    def __init__(self, approve: bool = True, identity: str = "auto-approver(non-human)"):
        self.approve = approve
        self.identity = identity

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(approved=self.approve, approver=self.identity, comment="automatic")


class FileApprover(Approver):
    """Persisted checkpoints for unattended runs.

    Approvals: `<stage>-<artifact sha>.request.json`, decided with `orch approve`. The id is the
    approved content's hash, so a decision can only ever apply to that exact content (a resumed
    run that produces something different needs a new decision).
    Clarifications: `<stage>-clarify-<round>-<questions hash>.questions.json` plus a readable
    `<id>.answers.yaml` to fill in, submitted with `orch answer`.
    Either way the recorded identity is the OS user who ran the command."""

    def __init__(self, directory: Path, *, poll_seconds: float = 1.0) -> None:
        self.directory = directory
        self.poll_seconds = poll_seconds
        self._counts: dict[str, int] = {}

    async def clarify(self, request: ClarificationRequest) -> ClarificationResponse:
        clarify_id = _clarify_id(request)
        questions_path = self.directory / f"{clarify_id}.questions.json"
        answered_path = self.directory / f"{clarify_id}.answered.json"
        if not questions_path.exists():
            write_atomic(questions_path, request.model_dump_json(indent=2))
            write_atomic(self.directory / f"{clarify_id}.answers.yaml", answers_template(request, clarify_id))
            print(f"[clarify]  {clarify_id}: {len(request.questions)} question(s) need a human answer\n"
                  f"           fill in: {self.directory / f'{clarify_id}.answers.yaml'}\n"
                  f"           submit : orch answer {request.run_id} {clarify_id}", flush=True)
        while not answered_path.exists():
            await asyncio.sleep(self.poll_seconds)
        return ClarificationResponse.model_validate_json(answered_path.read_text(encoding="utf-8"))

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        if request.artifact_sha:
            approval_id = f"{request.stage}-{request.artifact_sha[:12]}"
        else:
            n = self._counts[request.stage] = self._counts.get(request.stage, 0) + 1
            approval_id = f"{request.stage}-{n}"
        req_path = self.directory / f"{approval_id}.request.json"
        decision_path = self.directory / f"{approval_id}.decision.json"
        if not req_path.exists():
            write_atomic(req_path, request.model_dump_json(indent=2))
            print(f"[approval] {approval_id}: {request.reason}\n"
                  f"           review: orch pending {request.run_id}\n"
                  f"           decide: orch approve {request.run_id} {approval_id} [--reject] [--comment ...]",
                  flush=True)
        while not decision_path.exists():
            await asyncio.sleep(self.poll_seconds)
        return ApprovalDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))


def pending_approvals(directory: Path) -> list[tuple[str, ApprovalRequest]]:
    out = []
    for req_path in sorted(directory.glob("*.request.json")):
        approval_id = req_path.name.removesuffix(".request.json")
        if not (directory / f"{approval_id}.decision.json").exists():
            out.append((approval_id, ApprovalRequest.model_validate_json(req_path.read_text(encoding="utf-8"))))
    return out


def record_decision(directory: Path, approval_id: str, approved: bool, comment: str = "") -> ApprovalDecision:
    if not (directory / f"{approval_id}.request.json").exists():
        raise FileNotFoundError(f"no approval request '{approval_id}' in {directory}")
    decision_path = directory / f"{approval_id}.decision.json"
    if decision_path.exists():
        raise FileExistsError(f"'{approval_id}' was already decided")
    decision = ApprovalDecision(approved=approved, approver=getpass.getuser(), comment=comment)
    write_atomic(decision_path, decision.model_dump_json(indent=2))
    return decision


def answers_template(request: ClarificationRequest, clarify_id: str) -> str:
    header = (
        f"# Open questions from stage '{request.stage}' (run {request.run_id}, round {request.round}).\n"
        "# These are product decisions the agent would not guess. Fill in every `answer`,\n"
        f"# then submit:  orch answer {request.run_id} {clarify_id}\n"
        "# Your answers become binding human decisions in the audit log.\n\n"
    )
    items = [{"question": q["question"], "why": q.get("why", ""), "answer": ""} for q in request.questions]
    return header + yaml.safe_dump(items, sort_keys=False, allow_unicode=True, width=100)


def load_answers(path: Path) -> list[dict[str, str]]:
    items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a list of {{question, answer}} items")
    return [{"question": str(i["question"]), "answer": str(i.get("answer") or "").strip()} for i in items]


def pending_clarifications(directory: Path) -> list[tuple[str, ClarificationRequest]]:
    out = []
    for path in sorted(directory.glob("*.questions.json")):
        clarify_id = path.name.removesuffix(".questions.json")
        if not (directory / f"{clarify_id}.answered.json").exists():
            out.append((clarify_id, ClarificationRequest.model_validate_json(path.read_text(encoding="utf-8"))))
    return out


def record_answers(directory: Path, clarify_id: str, answers_file: Path | None = None) -> ClarificationResponse:
    """Validate that every question has an answer, then release the waiting run."""
    questions_path = directory / f"{clarify_id}.questions.json"
    if not questions_path.exists():
        raise FileNotFoundError(f"no clarification request '{clarify_id}' in {directory}")
    answered_path = directory / f"{clarify_id}.answered.json"
    if answered_path.exists():
        raise FileExistsError(f"'{clarify_id}' was already answered")
    request = ClarificationRequest.model_validate_json(questions_path.read_text(encoding="utf-8"))
    source_file = answers_file or directory / f"{clarify_id}.answers.yaml"
    by_question = {a["question"]: a for a in load_answers(source_file)}
    response = ClarificationResponse(
        answers=[{"question": q["question"], "answer": by_question.get(q["question"], {}).get("answer", "")}
                 for q in request.questions],
        answered_by=getpass.getuser(),
    )
    missing = response.missing(request)
    if missing:
        raise ValueError(f"{len(missing)} question(s) still need an answer in {source_file}: {missing}")
    write_atomic(answered_path, response.model_dump_json(indent=2))
    return response


class PresetAnswers(Approver):
    """Answers questions from a reviewed answers file (for deterministic replays), and
    defers anything it cannot answer, and every approval, to the wrapped approver.
    Recorded as `answers-file:<name>@<sha>`, never as a live human decision."""

    def __init__(self, path: Path, inner: Approver) -> None:
        self.inner = inner
        self.answers = {a["question"]: a["answer"] for a in load_answers(path) if a["answer"]}
        self.identity = f"answers-file:{path.name}@{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return await self.inner.decide(request)

    async def clarify(self, request: ClarificationRequest) -> ClarificationResponse | None:
        if all(q["question"] in self.answers for q in request.questions):
            return ClarificationResponse(
                answers=[{"question": q["question"], "answer": self.answers[q["question"]]} for q in request.questions],
                answered_by=self.identity, source="answers-file",
            )
        return await self.inner.clarify(request)


class CLIApprover(Approver):
    """Interactive terminal approval. Serialized so parallel stages don't interleave prompts."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        async with self._lock:
            return await asyncio.to_thread(self._prompt, request)

    async def clarify(self, request: ClarificationRequest) -> ClarificationResponse:
        async with self._lock:
            return await asyncio.to_thread(self._ask, request)

    @staticmethod
    def _ask(req: ClarificationRequest) -> ClarificationResponse:
        print(f"\n{'=' * 72}\nCLARIFICATION NEEDED  run={req.run_id}  stage={req.stage}  round={req.round}")
        answers = []
        for i, q in enumerate(req.questions, start=1):
            print(f"\n[{i}/{len(req.questions)}] {q['question']}\n      why: {q.get('why', '')}")
            answer = ""
            while not answer:
                answer = input("      answer: ").strip()
            answers.append({"question": q["question"], "answer": answer})
        return ClarificationResponse(answers=answers, answered_by=getpass.getuser())

    @staticmethod
    def _prompt(req: ApprovalRequest) -> ApprovalDecision:
        bar = "=" * 72
        lines = [
            "",
            bar,
            f"APPROVAL REQUIRED  run={req.run_id}  stage={req.stage}",
            f"Reason : {req.reason}",
            f"Summary: {req.summary}",
        ]
        if req.decisions:
            lines.append("Decisions:")
            lines += [f"  - {d}" for d in req.decisions]
        if req.files_changed:
            lines.append("Files changed:")
            lines += [f"  - {f}" for f in req.files_changed]
        if req.gate_evidence:
            lines.append("Gate evidence:")
            lines += [f"  - {g}" for g in req.gate_evidence]
        lines.append(bar)
        print("\n".join(lines))
        while True:
            answer = input("Approve? [y]es / [n]o: ").strip().lower()
            if answer in {"y", "yes", "n", "no"}:
                break
        comment = input("Comment (optional): ").strip()
        return ApprovalDecision(
            approved=answer.startswith("y"), approver=getpass.getuser(), comment=comment
        )

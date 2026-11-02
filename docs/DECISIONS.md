# Design decisions

Short records of the decisions that shaped the system: the context, the choice, and what it costs.

## Orchestrator

### D1. A small custom engine instead of LangGraph, Airflow or Temporal
**Context.** Governance (gates, policy, approvals, lineage, audit) is the graded part, and it has to be visible and owned.
**Decision.** A ~750-line asyncio scheduler over a declarative YAML DAG with an explicit state machine.
**Consequences.** Every rule is readable and testable in-repo. Single-process, single-node: a production version would move the event log to a database and the scheduler behind a queue (the event-sourced design carries over).

### D2. The event log is the source of truth (event sourcing), and it is hash-chained
**Decision.** Every transition, agent call, gate result, policy verdict, approval and artifact is an appended event; run state is rebuilt from the log; each event carries the previous event's hash.
**Consequences.** Pause, resume, replay, metrics and audit come from one mechanism. Tampering is detectable (`orch verify-audit`), and resume and reports refuse an unverifiable log. Not tamper-proof against someone who rewrites the whole chain (no external anchor).

### D3. Agents propose; only the orchestrator writes
**Decision.** Agents return a change set; it is scope-checked, policy-evaluated, possibly human-approved, and only then applied (`workspace/changes.py` is the single write path).
**Consequences.** A rejected attempt leaves no partial writes; a human approves risky changes before they exist on disk; rollback is exact. Agents that are trusted Python code could bypass this; LLM agents cannot, because they have no filesystem access.

### D4. Agents never judge their own output
**Decision.** Exit gates are run by the orchestrator (Maven builds, test-count floor, ambiguity resolution); approvals come after gates, so humans review verified output.
**Consequences.** An agent claiming success means nothing. Gates are only as strong as what they check (see RISKS).

### D5. One structured-output call per agent turn; the orchestrator owns the loop
**Decision.** No agent loops or tool use: a stable system prompt, one context message, a JSON schema generated from a Pydantic model that also validates the response.
**Consequences.** Every turn is governed, replayable and cheap to reason about. Agents cannot explore a codebase on their own; the context they see is chosen by `read_scope`.

### D6. Providers are configuration
**Decision.** A provider-neutral `LLMClient`, a registry, and per-agent routing in `config/llm.*.yaml`; SDKs are optional extras; no model names or prices hard-coded for providers whose catalogue changes.
**Consequences.** The project switched from Claude to OpenAI mid-way without touching agents, engine or policy. A third provider is one class.

### D7. Record/replay cassettes keyed by the full request
**Decision.** Each exchange is stored under a hash of model, prompt, context, schema and effort; `replay` fails on a miss instead of calling the API.
**Consequences.** Demos and CI are offline, deterministic and free; the four scenarios reproduce byte for byte. Any prompt or context change invalidates the matching recordings (by design), so prompt changes are deliberate events: new context an agent receives is opt-in per stage (`downstream_context`, `gate_context`), and the lifecycle replay uses the workflow file the run started with.

### D8. Human decisions are bound to content
**Decision.** An approval's id is the approved artifact's hash; a clarification's id is the hash of its question set.
**Consequences.** A decision can never be applied to different content, by a resume or a replay. Recorded decisions replay exactly (`--recorded-decisions`). The first greenfield run predates this, so its replay uses its reviewed answers file.

### D9. Ambiguity stops the pipeline; humans answer, bounded
**Decision.** The analyst must mark product decisions as unresolved rather than guess; an `ambiguities_resolved` gate stops the stage; a clarification checkpoint writes a readable answers file; answers are binding, recorded under the person's identity, and stamped onto the artifact. A non-human approver never answers.
**Consequences.** The ambiguous scenario turned three sentences into 23 requirements without inventing scope, and the analyst caught a contradiction in the answers. Bounded rounds mean a run can stop at the limit (it did twice); the fix was a reviewed workflow change, not an unbounded loop.

### D10. A rejection with a comment is a change request
**Decision.** Rejecting a workflow approval with a comment sends the comment back to the agent as a binding instruction (bounded by `max_revisions`); each revision allows one extra clarification round.
**Consequences.** Review can steer, not only veto: the ambiguous scenario's reviewer restored the existing error contract this way. A rejection without a comment stays final.

### D11. Policy as code with risk tiers
**Decision.** Rules in `policies/default.yaml` map to actions (`allow`, `flag`, `require_approval`, `reject`, `block`); the strictest wins; workflows cannot opt out; the policy file's hash is recorded on every run.
**Consequences.** Low-risk work flows; risky work waits for a person; changing what is blocked is itself a reviewable change. Rules are pattern-based, not semantic.

### D12. Least privilege both ways
**Decision.** `read_scope` bounds what an agent sees; `write_scope` what it may change; context above ~100k tokens is refused, not truncated.
**Consequences.** Secrets and unrelated files never reach a prompt; a breach of scope fails the stage immediately.

### D13. File-level rollback, git checkpoints, and an isolated default workspace
**Decision.** Revert exactly the files an attempt wrote (only if unchanged since); commit one checkpoint per accepted stage; default to `runs/<id>/workspace`; touch an existing repository only when clean and only on `orch/<run-id>`.
**Consequences.** Parallel stages share a workspace safely; the branch history reads as the delivery history; the person's branch is never modified.

### D14. Re-planning by lineage
**Decision.** Invalidated stages become `STALE` with their old artifact kept; downstream stages are reused when the artifacts they were built from are unchanged and re-run otherwise.
**Consequences.** A change propagates only as far as it reaches; reused artifacts keep their approvals. Re-planning applies between processes (resume/replan), not mid-flight.

### D15. Hybrid backends, labelled honestly
**Decision.** For cost, the coder and tester were served by an assistant session (Claude Code) through files, with the same prompts, context, schema, policy and gates as an API model; their calls are recorded as `claude-code-session` at $0.
**Consequences.** The audit trail shows exactly who produced what. Those stages were served by a capable assistant that also verified its work before answering, so the live runs saw no gate failures; retries and rollbacks are therefore demonstrated by tests and `demo-fault-injection` rather than by the live runs.

### D16. Metrics only from the log
**Decision.** `orch report` computes everything from the verified event log, with explicit definitions (failure retries vs clarifications; incidents and MTTR; human wait merged across parallel stages; replayed decisions counted once).
**Consequences.** Any number is recomputable by a reviewer. Definitions were corrected against real runs (see RISKS, "lessons").

### D17. The API definition is a gated, approved artifact, checked against the code both ways
**Context.** The assignment asks for API definitions; a definition that drifts from the code is worse than none.
**Decision.** A design stage produces the complete OpenAPI definition before implementation, validated by a real OpenAPI validator and approved by a person. Implementation has an entry gate (the definition is still valid) and an exit gate that compares the documented operations with the Spring mappings in the code, in both directions. Documentation must cover every documented path; release re-runs the full suite as an entry gate and is blocked by any failing checklist item.
**Consequences.** Design-to-code traceability is enforced, not described. The conformance scan reads annotations statically (method and path, not request or response shapes), so schema-level drift is caught only by tests and review.

### D18. Bugs are reproduced before they are fixed, and the order is enforced
**Context.** A fix that passes the tests proves nothing if no test ever failed: the bug may never have been understood, or the test may not test it.
**Decision.** The bug-fix workflow puts a reproduce stage (tests only) before the fix stage (code only). Its gate clears old reports, runs the suite, and passes only if the tests compile, at least one new test fails, and nothing else fails; the fix stage cannot write tests and must make the whole suite pass.
**Consequences.** Every bug fix comes with a regression test that is known to have failed on the old code and to pass on the new. Whether a test fails for the *reported* reason is still a human judgement; the gate shows each failure's message to support it. Release readiness reads the orchestrator's gate results (`gate_context`), not agents' summaries.

### D19. A model proposes the workflow; rules bound it and a person confirms it
**Context.** Choosing the workflow decides which risks a change is governed for: a bug fixed without reproduction, or an API change shipped without docs, starts with the wrong choice.
**Decision.** Eligibility is a rule over facts (does the codebase exist), not a model judgement. Among the eligible workflows a selector agent proposes one, through a schema whose enum holds only their names, with confidence, rationale, the signals it relied on and a runner-up. A person confirms; a commented rejection is a bounded change request. The selection is recorded in `RUN_STARTED`.
**Consequences.** The model cannot pick an ineligible or invented workflow, and low confidence is visible to the person confirming. Workflows are chosen, not composed: a requirement that needs a new shape of process still needs a new workflow file. The eval (9 cases, 9 correct) is small and written by the same author as the `use_when` texts, so it guards against regressions rather than proving accuracy.

### D20. Coverage and a real-server smoke test as release gates, without touching the service's build
**Context.** Gates checked that tests pass, not how much they exercise, and every test ran in-process.
**Decision.** A coverage gate runs JaCoCo by its plugin coordinates (85% of lines overall, 80% in each production file the change touched, explicit excludes); a smoke gate builds the jar, starts it on free ports with a temporary data directory, runs declarative HTTP steps from the workflow, and always stops it.
**Consequences.** Weakly tested changes and a packaged service that does not start or answer correctly block a release. The smoke gate found a real defect on its first use (HTML errors from Tomcat). The smoke steps are specific to this service and live in the workflow files; a second service would bring its own.

## URL shortener

| # | Decision | Why |
|---|---|---|
| S1 | File-based H2 + Flyway, Hibernate `validate` | Runs anywhere with one command; schema is versioned and verified; the upgrade path was tested on a real v1 database |
| S2 | Tombstones: deleted links keep their row, URL and token erased; codes never reused | A shared old link must never start pointing somewhere new |
| S3 | Management token: 256-bit, stored as SHA-256, compared in constant time; missing → 401, wrong → 403 | No plaintext at rest; no timing side channel; distinct client errors |
| S4 | Destination policy checked once at creation, DNS fail-closed, IPv6 unique-local covered explicitly | The service never fetches destinations, so re-pointing DNS later is an accepted limitation |
| S5 | Click recording best-effort, in its own transaction; row lock shared with deletion | Redirecting is the product (owner decision); the lock makes erase-on-delete race-free |
| S6 | Stats private (token), 30 UTC days, counts only, no visitor identifiers | Owner decisions; privacy requirement made testable |
| S7 | One JSON error schema; existing codes authoritative; framework errors translated | Consistency without breaking clients (the reviewer's change request) |
| S8 | Actuator on a loopback-only management port, health and metrics only | Operator visibility without an authentication system |
| S9 | 503 + `Retry-After: 5` only when the redirect's link lookup cannot reach the store | Explicit outage behaviour without turning analytics failures into failed redirects |

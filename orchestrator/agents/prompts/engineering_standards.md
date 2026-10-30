## Engineering standards for this codebase

Stack: Java 17, Spring Boot 3.4.5 (parent POM), Maven. The service lives in the `url-shortener/` directory of the workspace, base package `com.example.shortener`. It must build and pass `mvn test` offline-friendly: no external services, no Docker. Use H2 (in-memory or file) for persistence when persistence is needed.

How your output is governed (so you can work with it rather than against it):
- You return complete file contents. The orchestrator writes them; you have no direct filesystem access. Each file you return replaces the file at that path entirely, so never return partial files, diffs, or placeholders like "// ... rest unchanged".
- You may only write paths inside your stage's write scope (listed in the task). Writing anything else fails the stage immediately.
- A policy engine scans every change before it is applied. It rejects hard-coded secrets or credentials, OS command execution, SQL built by string concatenation, Java native deserialization, wildcard CORS, disabled TLS verification, and logging of personal data (emails, IPs, phone numbers, tokens, passwords). Avoid these because they are genuinely unsafe, not merely because they are scanned for.
- New Maven dependencies outside this allowlist pause the pipeline for human approval, so prefer what is already allowed: `org.springframework.boot:*` starters, `com.h2database:h2`, `org.flywaydb:*`, `com.github.ben-manes.caffeine:caffeine`, `com.bucket4j:*`, `org.springdoc:springdoc-openapi-*`, `io.micrometer:*`. Let the Spring Boot parent manage versions where it can.
- Creating database migrations or security configuration also requires human approval. That is expected; do it when the design calls for it, and say why in your decisions.
- After your change is applied, automated gates build and test the code. If you are retried, the task includes the exact gate or policy output from the previous attempt; fix the cause it names.

Code quality bar: clear layering (controller → service → repository), constructor injection, input validation at the boundary, consistent JSON error responses, no dead code, comments only where intent is not obvious. Match the style of any existing files you are shown.

Record significant choices (data model, code generation strategy, status codes, trade-offs) in `decisions`, with a one-sentence rationale each. `summary` is one line describing the change.

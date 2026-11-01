# Session request: tester

Write the response as JSON matching the schema to:
`runs/live-ambiguous-1/llm-requests/tester-d1768e8f0793ef9a.response.json`
(or use `orch respond runs/live-ambiguous-1/llm-requests/tester-d1768e8f0793ef9a.request.json ...`)

## System prompt

You are the test engineer in a governed software delivery pipeline. You turn the approved test plan into automated JUnit 5 tests for the implementation you are shown, under `url-shortener/src/test/`. The orchestrator then runs `mvn test`; your stage passes only if the build and every test pass.

- Implement every case in the test plan, keeping its id in the test method name or a short comment so results trace back to requirements.
- Integration cases: `@SpringBootTest` with `@AutoConfigureMockMvc`, asserting status codes, headers and JSON bodies. Unit cases: plain JUnit with the class under test constructed directly.
- Tests must be deterministic and independent: no reliance on execution order, wall-clock timing, or shared mutable state between tests (use unique inputs per test or reset state).
- Test the behaviour the specification requires. If the implementation you are shown contradicts the specification, do not weaken the test to make it pass: keep the test faithful to the specification and record the discrepancy as a decision with topic "implementation defect", naming the requirement and the observed behaviour.
- If you are retried with `mvn test` output, read it carefully: fix compilation errors and genuine test mistakes; for failures caused by an implementation defect, follow the rule above.

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

## Task

<approved_specification>
{
  "acceptance_criteria": [
    "Given a pre-existing active link, when it is requested, then it redirects to the same destination with identical behaviour; a check against the stored link data confirms retention was not changed.",
    "Given an expired link, when it is requested, then the response is 410 with error code expired. Given a deleted or unknown code, then the response is 404 with error code not_found.",
    "Given invalid input or a conflict, when the corresponding request is made, then it returns the existing 400 or 409 response and retains the existing error code.",
    "Given a management request without a token, when it reaches stats or delete, then it returns 401 with error code missing_token and does not increment the failed-token counter. Given an incorrect token below the limit, then it returns 403 with error code invalid_token.",
    "Given 10 supplied-but-incorrect management-token attempts from the same client IP within a rolling 60 seconds across stats and delete, when another incorrect token is supplied, then the response is 429 with error code rate_limited, a Retry-After header, and the standard JSON error body. A valid token continues to be processed.",
    "Given the existing create limit of 20 creates per minute per client IP has been reached, when another create is attempted, then the response is 429 with error code rate_limited and a Retry-After header.",
    "Given a redirect request while the database is unavailable, when the redirect is handled, then the response is 503 with error code service_unavailable, Retry-After: 5, and the standard JSON error body; the service does not retry on the client's behalf.",
    "Given an active link while the service and database are available, when it is redirected, then it does not receive a 5xx response. Given an unexpected error, then the response is 500 with error code internal_error and contains no stack trace or internal details.",
    "Given an unsupported method, an unmatched route, or an oversized API request, when the request is made, then the response uses the standard JSON error body and the agreed status and code: 405 method_not_allowed, 404 not_found, or 413 payload_too_large as applicable.",
    "Given an otherwise valid request to /api/** with a body of at most 16,384 bytes, when it is processed, then it is not rejected for body size. Given a body larger than 16,384 bytes, then it returns 413 with error code payload_too_large.",
    "Given any response, including redirects, errors, public health, and Actuator responses, when its headers are inspected, then all four specified security headers and values are present.",
    "Given redirect traffic with 302, 404, 410, and 5xx outcomes, when the local Actuator metrics endpoint is queried, then the outcome counts and redirect timings are observable, and 404s are not split by cause.",
    "Given a request from outside the host, when it attempts to reach Actuator, then the management endpoints are unreachable. Given a host-local request, then only Actuator health and metrics are exposed on the separate management port; the existing main-port /health endpoint remains unchanged.",
    "Given a sequence of link-code probes, when unknown codes are requested, then no link-code rate limit is applied and the redirect metric records aggregate 404 outcomes.",
    "Given redirect load in the existing in-process latency check, when the check runs, then the redirect p99 remains below 50 ms.",
    "Given visitor requests, when service logs are inspected, then the change has added no visitor-specific logging. Redirect handling also performs no destination-reachability check or destination retry.",
    "Before release, all existing and new tests pass, the suite contains at least 95 tests, automated tests cover security headers and error behaviour, and the product owner has approved the release."
  ],
  "ambiguities": [
    {
      "question": "Which pre-existing links are in scope, and for how long must they continue to work (including expired, deleted, or otherwise inactive links)?",
      "rationale": "Decided by a human: This defines the compatibility and retention requirements for existing active, expired, and deleted links.",
      "resolution": "Every active link keeps resolving to the same destination with identical behaviour. Expired links keep returning 410 and deleted links 404, as today. No change to how long links or tombstones are retained.",
      "source": "assumption"
    },
    {
      "question": "Which reliability measures and targets define \u201cmore reliable\u201d (for example, availability, resolution success, latency, or recovery time)?",
      "rationale": "Decided by a human: These are the required reliability measures and targets; the database-outage exception is specified separately below.",
      "resolution": "Reliability is measured by redirect outcomes and latency, exposed as metrics through Spring Boot Actuator and Micrometer: count redirects by outcome (302, 404, 410, 5xx) and time them. Target: an active link never receives a 5xx while the service is running, and the existing in-process redirect p99 < 50 ms check keeps passing.",
      "source": "assumption"
    },
    {
      "question": "What failures have users experienced, how often do they occur, and which shortener workflows or user groups are affected?",
      "rationale": "Decided by a human: The release should make failures observable rather than assume and change behaviour to fix an unconfirmed cause.",
      "resolution": "There is no incident data, only anecdotal reports. The goal is to make failures measurable and diagnosable (per-outcome redirect metrics, consistent JSON errors), not to fix a guessed bug. Likely causes to confirm with the metrics: expired links (410) and aliases typed with the wrong case.",
      "source": "assumption"
    },
    {
      "question": "What threats, attackers, and attack surfaces must the security work address, and what residual risk is acceptable?",
      "rationale": "Decided by a human: This defines the threat model and accepted residual risks for the release.",
      "resolution": "A public-internet attacker who probes codes and management tokens, floods link creation, sends oversized or malformed requests, or tries to extract internal details from error responses, plus browser-side attacks such as framing or content sniffing. Accepted residual risk for this release: no URL reputation or malware scanning of destinations, no authentication system beyond management tokens.",
      "source": "assumption"
    },
    {
      "question": "Which service components, integrations, and deployment environments are in scope for reliability and security changes?",
      "rationale": "Decided by a human: This sets the implementation boundary for the work.",
      "resolution": "Only the url-shortener service, running as a single node. No infrastructure, deployment or third-party integration changes.",
      "source": "assumption"
    },
    {
      "question": "What should happen for failed, malformed, unknown, or unreachable links, including response behavior, status codes, and retry behavior?",
      "rationale": "Decided by a human: These response and retry behaviours are binding; the reviewer\u2019s exact error-code contract is also captured in FR8.",
      "resolution": "Keep the existing contract: 400 for invalid input, 404 for unknown or deleted codes, 410 for expired links. If the database is unavailable during a redirect, return 503 with a Retry-After header and the standard JSON error body instead of an unhandled 500. Any other unexpected error returns a 500 JSON error without internal details. The service never checks whether a destination is reachable and never retries on the client's behalf.",
      "source": "assumption"
    },
    {
      "question": "What broader-rollout decision or release gate must the reliability and security work satisfy?",
      "rationale": "Decided by a human: These are the required test and approval gates for release.",
      "resolution": "All existing tests and the new tests pass (the suite must not drop below its current 95 tests), the security headers and error behaviour are covered by automated tests, and the product owner approves the release.",
      "source": "assumption"
    },
    {
      "question": "What maximum request-body size should the JSON API enforce?",
      "rationale": "Decided by a human: This sets the body-size limit and the response for requests that exceed it.",
      "resolution": "16 KB for requests to /api/**, well above the largest valid create request. A larger body is rejected with 413 Payload Too Large and the standard JSON error body.",
      "source": "assumption"
    },
    {
      "question": "What controls and thresholds should protect against link-code or management-token probing and link-creation floods, including the response to requests that exceed those limits?",
      "rationale": "Decided by a human: This specifies both rate limits, their response behaviour, and the accepted residual risk for code probing.",
      "resolution": "Link-creation floods: keep the existing limit of 20 creates per minute per client IP (429 with Retry-After). Management-token probing: add a limit of 10 failed management-token attempts per minute per client IP, counted across the stats and delete endpoints; further attempts get 429 with Retry-After and the standard JSON error body. Link-code probing: no limit in this release, because 64^8 (about 2.8e14) possible codes makes brute force impractical and limiting 404s would hurt users with typos; this is an accepted residual risk, observable through the 404 redirect metric.",
      "source": "assumption"
    },
    {
      "question": "Who may access the Actuator health and metrics endpoints?",
      "rationale": "Decided by a human: Access to Actuator is restricted to the host; the public health endpoint remains unchanged.",
      "resolution": "Only operators on the host. Serve the Actuator endpoints on a separate management port bound to 127.0.0.1, so they are unreachable from the public interface and no new authentication system is needed. The existing public /health endpoint on the main port stays as it is.",
      "source": "assumption"
    },
    {
      "question": "What is the standard JSON error-body schema, including its fields and message format?",
      "rationale": "Decided by a human: This defines the error envelope and requires it for application and framework-generated errors.",
      "resolution": "Keep the existing schema {\"error\": \"<stable machine-readable code>\", \"message\": \"<human-readable text>\"} and use it for every error response, including framework-generated ones such as unmatched routes, 405, 413, 500 and 503.",
      "source": "assumption"
    },
    {
      "question": "Does the target that an active link never receives a 5xx while the service is running exclude database outages, or must the 503 database-unavailable response be changed?",
      "rationale": "Decided by a human: The reliability target excludes database outages, for which 503 is explicitly intended.",
      "resolution": "The target applies while the service and its database are available: then an active link never receives a 5xx. During a database outage the 503 with Retry-After is the intended, explicit behaviour.",
      "source": "assumption"
    },
    {
      "question": "Must redirect metrics distinguish 404 causes, such as unknown codes, deleted codes, or aliases entered with the wrong case, or is an aggregate 404 outcome sufficient?",
      "rationale": "Decided by a human: Metrics must aggregate 404 outcomes; per-cause diagnosis is out of scope.",
      "resolution": "An aggregate 404 outcome is sufficient. No per-cause breakdown: it would add queries on the redirect hot path and record more about requests than needed. Diagnosing wrong-case aliases is out of scope for this release.",
      "source": "assumption"
    },
    {
      "question": "What Retry-After delay or date should the 503 response use when the database is unavailable?",
      "rationale": "Decided by a human: The database-unavailable redirect response must use a five-second Retry-After value.",
      "resolution": "Retry-After: 5 (seconds). Short enough that users are not kept waiting, long enough that clients do not hammer a database that is recovering.",
      "source": "assumption"
    },
    {
      "question": "Do missing management tokens count toward the 10 failed management-token attempts per client IP, or does the limit count only supplied but incorrect tokens?",
      "rationale": "Decided by a human: Missing tokens must not count toward the failed-token limit and must receive the specified 401 response.",
      "resolution": "Only supplied-but-incorrect tokens count toward the 10 failed attempts per minute per client IP. A request without a token always gets 401 missing_token and does not count: it is a client bug, not token guessing, and counting it would let one misconfigured client on a shared IP lock others out.",
      "source": "assumption"
    },
    {
      "question": "How should the 16 KB request-body limit be measured: as decimal or binary kilobytes, and against the declared length or the bytes actually received?",
      "rationale": "16 KiB is a conventional interpretation for software-configured payload limits; enforcing actual received bytes prevents a missing or inaccurate Content-Length from bypassing the limit.",
      "resolution": "Interpret 16 KB as 16 KiB (16,384 bytes) and enforce the limit against the request-body bytes actually received; reject bodies larger than 16,384 bytes.",
      "source": "assumption"
    },
    {
      "question": "What time-window algorithm defines the new per-minute failed management-token limit?",
      "rationale": "A rolling window is a conventional, straightforward interpretation of per-minute limits and avoids allowing a large burst across adjacent fixed-window boundaries.",
      "resolution": "Use a rolling 60-second window for failed management-token attempts.",
      "source": "assumption"
    },
    {
      "question": "How should the service identify the client IP for per-IP limits when forwarding headers are present?",
      "rationale": "Without a specified trusted-proxy setup, trusting caller-supplied forwarding headers would allow IP spoofing and rate-limit evasion; using the connection peer is the secure conventional default.",
      "resolution": "Use the direct connection peer address and do not trust Forwarded or X-Forwarded-For headers unless a trusted-proxy configuration is explicitly provided.",
      "source": "assumption"
    },
    {
      "question": "What Retry-After value should the new failed-management-token limit return?",
      "rationale": "Delta-seconds is a standard HTTP form and gives a client an actionable wait time without requiring a client/server clock comparison.",
      "resolution": "Return Retry-After as delta-seconds indicating when the next incorrect-token attempt may be admitted.",
      "source": "assumption"
    },
    {
      "question": "After an IP has reached the failed management-token limit, should requests with a valid token also be rejected?",
      "rationale": "Throttling only incorrect attempts is a conventional low-risk choice that preserves authorized access and avoids letting an attacker lock out users sharing an IP.",
      "resolution": "Continue processing valid-token requests; return 429 for further supplied-but-incorrect token attempts while the limit remains in effect.",
      "source": "assumption"
    },
    {
      "question": "What Content-Type should error responses using the JSON error schema declare?",
      "rationale": "application/json is the conventional media type for the specified JSON response body.",
      "resolution": "Declare Content-Type: application/json for error responses.",
      "source": "assumption"
    },
    {
      "question": "Which paths should expose Actuator health and metrics on the management port?",
      "rationale": "The default Actuator paths are conventional and make the specified health and metrics endpoints explicit without adding new endpoint scope.",
      "resolution": "Use the Spring Boot Actuator defaults: /actuator/health and /actuator/metrics, with no other Actuator endpoints exposed.",
      "source": "assumption"
    }
  ],
  "change_requests": [
    "Keep the existing error contract exactly: missing token 401 missing_token; wrong token 403 invalid_token; 404 not_found; 410 expired; 429 rate_limited (also for the new failed-token limit); existing 400/409 codes unchanged. New codes only for new cases: 405 method_not_allowed, 413 payload_too_large, 500 internal_error, 503 service_unavailable."
  ],
  "clarifications": [
    {
      "answer": "Every active link keeps resolving to the same destination with identical behaviour. Expired links keep returning 410 and deleted links 404, as today. No change to how long links or tombstones are retained.",
      "question": "Which pre-existing links are in scope, and for how long must they continue to work (including expired, deleted, or otherwise inactive links)?"
    },
    {
      "answer": "Reliability is measured by redirect outcomes and latency, exposed as metrics through Spring Boot Actuator and Micrometer: count redirects by outcome (302, 404, 410, 5xx) and time them. Target: an active link never receives a 5xx while the service is running, and the existing in-process redirect p99 < 50 ms check keeps passing.",
      "question": "Which reliability measures and targets define \u201cmore reliable\u201d (for example, availability, resolution success, latency, or recovery time)?"
    },
    {
      "answer": "There is no incident data, only anecdotal reports. The goal is to make failures measurable and diagnosable (per-outcome redirect metrics, consistent JSON errors), not to fix a guessed bug. Likely causes to confirm with the metrics: expired links (410) and aliases typed with the wrong case.",
      "question": "What failures have users experienced, how often do they occur, and which shortener workflows or user groups are affected?"
    },
    {
      "answer": "A public-internet attacker who probes codes and management tokens, floods link creation, sends oversized or malformed requests, or tries to extract internal details from error responses, plus browser-side attacks such as framing or content sniffing. Accepted residual risk for this release: no URL reputation or malware scanning of destinations, no authentication system beyond management tokens.",
      "question": "What threats, attackers, and attack surfaces must the security work address, and what residual risk is acceptable?"
    },
    {
      "answer": "Add standard security headers to every response (X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: no-referrer, Content-Security-Policy: default-src 'none'; frame-ancestors 'none'), a request body size limit for the JSON API, and error responses that never include stack traces or internal details. Log nothing new about visitors. Actuator exposes only the health and metrics endpoints. No compliance regime applies to this release.",
      "question": "Which security controls or data-handling requirements are expected, including requirements for access, privacy, logging, or compliance?"
    },
    {
      "answer": "Only the url-shortener service, running as a single node. No infrastructure, deployment or third-party integration changes.",
      "question": "Which service components, integrations, and deployment environments are in scope for reliability and security changes?"
    },
    {
      "answer": "Keep the existing contract: 400 for invalid input, 404 for unknown or deleted codes, 410 for expired links. If the database is unavailable during a redirect, return 503 with a Retry-After header and the standard JSON error body instead of an unhandled 500. Any other unexpected error returns a 500 JSON error without internal details. The service never checks whether a destination is reachable and never retries on the client's behalf.",
      "question": "What should happen for failed, malformed, unknown, or unreachable links, including response behavior, status codes, and retry behavior?"
    },
    {
      "answer": "All existing tests and the new tests pass (the suite must not drop below its current 95 tests), the security headers and error behaviour are covered by automated tests, and the product owner approves the release.",
      "question": "What broader-rollout decision or release gate must the reliability and security work satisfy?"
    },
    {
      "answer": "16 KB for requests to /api/**, well above the largest valid create request. A larger body is rejected with 413 Payload Too Large and the standard JSON error body.",
      "question": "What maximum request-body size should the JSON API enforce?"
    },
    {
      "answer": "Link-creation floods: keep the existing limit of 20 creates per minute per client IP (429 with Retry-After). Management-token probing: add a limit of 10 failed management-token attempts per minute per client IP, counted across the stats and delete endpoints; further attempts get 429 with Retry-After and the standard JSON error body. Link-code probing: no limit in this release, because 64^8 (about 2.8e14) possible codes makes brute force impractical and limiting 404s would hurt users with typos; this is an accepted residual risk, observable through the 404 redirect metric.",
      "question": "What controls and thresholds should protect against link-code or management-token probing and link-creation floods, including the response to requests that exceed those limits?"
    },
    {
      "answer": "Only operators on the host. Serve the Actuator endpoints on a separate management port bound to 127.0.0.1, so they are unreachable from the public interface and no new authentication system is needed. The existing public /health endpoint on the main port stays as it is.",
      "question": "Who may access the Actuator health and metrics endpoints?"
    },
    {
      "answer": "Keep the existing schema {\"error\": \"<stable machine-readable code>\", \"message\": \"<human-readable text>\"} and use it for every error response, including framework-generated ones such as unmatched routes, 405, 413, 500 and 503.",
      "question": "What is the standard JSON error-body schema, including its fields and message format?"
    },
    {
      "answer": "The target applies while the service and its database are available: then an active link never receives a 5xx. During a database outage the 503 with Retry-After is the intended, explicit behaviour.",
      "question": "Does the target that an active link never receives a 5xx while the service is running exclude database outages, or must the 503 database-unavailable response be changed?"
    },
    {
      "answer": "An aggregate 404 outcome is sufficient. No per-cause breakdown: it would add queries on the redirect hot path and record more about requests than needed. Diagnosing wrong-case aliases is out of scope for this release.",
      "question": "Must redirect metrics distinguish 404 causes, such as unknown codes, deleted codes, or aliases entered with the wrong case, or is an aggregate 404 outcome sufficient?"
    },
    {
      "answer": "Retry-After: 5 (seconds). Short enough that users are not kept waiting, long enough that clients do not hammer a database that is recovering.",
      "question": "What Retry-After delay or date should the 503 response use when the database is unavailable?"
    },
    {
      "answer": "Only supplied-but-incorrect tokens count toward the 10 failed attempts per minute per client IP. A request without a token always gets 401 missing_token and does not count: it is a client bug, not token guessing, and counting it would let one misconfigured client on a shared IP lock others out.",
      "question": "Do missing management tokens count toward the 10 failed management-token attempts per client IP, or does the limit count only supplied but incorrect tokens?"
    }
  ],
  "functional": [
    {
      "id": "FR1",
      "text": "Every pre-existing active link must continue to resolve to the same destination with identical behaviour."
    },
    {
      "id": "FR2",
      "text": "Do not change how long links or tombstones are retained."
    },
    {
      "id": "FR3",
      "text": "Preserve the existing 400 response and error code for invalid input and the existing 409 response and error code for conflicts."
    },
    {
      "id": "FR4",
      "text": "A management request without a token must return 401 with error code missing_token; a request with an incorrect token must return 403 with error code invalid_token, unless the failed-token rate limit requires 429."
    },
    {
      "id": "FR5",
      "text": "Unknown and deleted link codes must return 404 with error code not_found. Expired links must return 410 with error code expired."
    },
    {
      "id": "FR6",
      "text": "If the database is unavailable during a redirect, return 503 with error code service_unavailable and Retry-After: 5. Do not retry the database operation on the client's behalf."
    },
    {
      "id": "FR7",
      "text": "An unexpected error must return 500 with error code internal_error and must not expose stack traces or internal details."
    },
    {
      "id": "FR8",
      "text": "Every error response, including framework-generated errors and unmatched routes, must use the JSON object with fields error and message. Use the agreed status/code pairs: 401 missing_token, 403 invalid_token, 404 not_found, 405 method_not_allowed, 410 expired, 413 payload_too_large, 429 rate_limited, 500 internal_error, and 503 service_unavailable. Existing 400 and 409 error codes must remain unchanged."
    },
    {
      "id": "FR9",
      "text": "Keep the existing link-creation limit of 20 creates per minute per client IP. Requests exceeding it must return 429 with error code rate_limited and a Retry-After header."
    },
    {
      "id": "FR10",
      "text": "Limit supplied-but-incorrect management-token attempts to 10 per minute per client IP, counted across the stats and delete endpoints. Further incorrect-token attempts must return 429 with error code rate_limited and a Retry-After header. Requests without a token must return 401 missing_token and must not count toward this limit."
    },
    {
      "id": "FR11",
      "text": "Do not rate-limit link-code probing in this release. Redirect 404 metrics must aggregate unknown and deleted codes without a per-cause breakdown."
    },
    {
      "id": "FR12",
      "text": "Enforce a 16 KB request-body limit for requests to /api/**. A body exceeding the limit must return 413 with error code payload_too_large and the standard JSON error body."
    },
    {
      "id": "FR13",
      "text": "Add these headers to every service response: X-Content-Type-Options: nosniff; X-Frame-Options: DENY; Referrer-Policy: no-referrer; Content-Security-Policy: default-src 'none'; frame-ancestors 'none'."
    },
    {
      "id": "FR14",
      "text": "Expose redirect outcome counts for 302, 404, 410, and 5xx responses, and measure redirect request time, using Spring Boot Actuator and Micrometer. Do not add a per-cause breakdown for 404 outcomes."
    },
    {
      "id": "FR15",
      "text": "Expose only Actuator health and metrics endpoints on a separate management port bound to 127.0.0.1."
    },
    {
      "id": "FR16",
      "text": "Keep the existing public /health endpoint on the main port unchanged."
    },
    {
      "id": "FR17",
      "text": "Do not add logging about visitors."
    },
    {
      "id": "FR18",
      "text": "Do not check whether a destination URL is reachable, retry destination requests, scan destinations for reputation or malware, or add an authentication system beyond the existing management tokens."
    },
    {
      "id": "FR19",
      "text": "Limit this work to the url-shortener service running as a single node. Do not make infrastructure, deployment, or third-party integration changes."
    }
  ],
  "goal": "Improve reliability and security of the single-node url-shortener service without changing how existing active links resolve or changing retention for expired or deleted links. Make redirect outcomes measurable, enforce the agreed request and token controls, and preserve the specified response contract.",
  "non_functional": [
    {
      "id": "NFR1",
      "text": "While the service and its database are available, an active link must not receive a 5xx response. A database outage is excluded from this target and must follow the explicit 503 behaviour in FR6."
    },
    {
      "id": "NFR2",
      "text": "The existing in-process redirect p99 latency check must continue to pass with a target below 50 ms."
    },
    {
      "id": "NFR3",
      "text": "Do not add visitor-specific information to logs."
    },
    {
      "id": "NFR4",
      "text": "All existing and new tests must pass, and the test suite must contain at least the current 95 tests. Automated tests must cover the security headers and error behaviour. Release requires product-owner approval."
    }
  ]
}
</approved_specification>

<approved_impact_analysis>
{
  "api_changes": [
    {
      "change": "Existing endpoint request and success-response contracts remain unchanged unless a requirement below explicitly adds behavior. Existing 400 and 409 status codes and error codes remain unchanged. Errors use application/json with {\"error\":\"<stable code>\",\"message\":\"<human-readable text>\"}; all responses receive the specified security headers.",
      "method": "ALL",
      "path": "Existing endpoints"
    },
    {
      "change": "Request remains CreateLinkRequest JSON. Existing success remains 201 with CreateLinkResponse; existing invalid-input and conflict responses retain their current codes; the existing 20-per-minute-per-direct-peer limit remains 429 rate_limited with Retry-After. New: bodies over 16,384 actual bytes return 413 payload_too_large with the standard JSON error body.",
      "method": "POST",
      "path": "/api/links"
    },
    {
      "change": "Request remains the code path parameter. Existing 200 LinkMetadata and 404 not_found behavior remain unchanged; unexpected errors use 500 internal_error with no internal details.",
      "method": "GET",
      "path": "/api/links/{code}"
    },
    {
      "change": "Request remains the code path parameter and optional X-Management-Token header. Existing 200 StatsResponse, 401 missing_token, 403 invalid_token, and 404 not_found contracts remain; the 11th and subsequent supplied incorrect attempts within the rolling limit return 429 rate_limited with Retry-After. Missing tokens do not count.",
      "method": "GET",
      "path": "/api/links/{code}/stats"
    },
    {
      "change": "Request remains the code path parameter and optional X-Management-Token header. Existing 204, 401 missing_token, 403 invalid_token, and 404 not_found contracts remain; the 11th and subsequent supplied incorrect attempts within the shared rolling limit return 429 rate_limited with Retry-After. Missing tokens do not count.",
      "method": "DELETE",
      "path": "/api/links/{code}"
    },
    {
      "change": "Request remains a GET to a matching short-code path. Active links retain the same 302 Location and Cache-Control: no-store behavior; unknown/deleted codes remain 404 not_found and expired codes remain 410 expired. A database failure during the required link lookup returns 503 service_unavailable, Retry-After: 5, and the standard JSON error body; unexpected errors return 500 internal_error. Redirect requests are not retried.",
      "method": "GET",
      "path": "/{code}"
    },
    {
      "change": "Request and existing 200/503 status JSON contract remain unchanged; the response gains the required security headers.",
      "method": "GET",
      "path": "/health"
    },
    {
      "change": "New endpoint on the separate management port bound to 127.0.0.1 only; uses the standard Actuator health response.",
      "method": "GET",
      "path": "/actuator/health"
    },
    {
      "change": "New endpoint on the separate management port bound to 127.0.0.1 only; uses the standard Actuator metrics response and exposes redirect outcome counts and timing measurements.",
      "method": "GET",
      "path": "/actuator/metrics"
    },
    {
      "change": "Bodies larger than 16,384 bytes as actually received return 413 payload_too_large with application/json and the standard error fields; bodies at or below the limit are not rejected for size.",
      "method": "ANY",
      "path": "/api/**"
    },
    {
      "change": "Return 405 method_not_allowed with the standard JSON error body.",
      "method": "Unsupported methods",
      "path": "Routed endpoints"
    },
    {
      "change": "Return 404 not_found with the standard JSON error body.",
      "method": "ANY",
      "path": "Unmatched routes"
    }
  ],
  "data_changes": [
    "No schema or persisted-data changes are required; rate-limit state and Micrometer measurements remain in memory.",
    "No migration file is required. Existing V1__create_links.sql and V2__create_click_events.sql remain immutable; no retention, tombstone, or click-event storage changes are planned."
  ],
  "data_flows": [
    "Redirect hot path: resolve the code with the existing indexed link lookup; map lookup database availability failures to the specified 503 without retry; return the existing 302 for an active link; attempt click recording as existing best-effort work; record outcome and elapsed time with fixed, low-cardinality metric tags. Do not query for 404 causes, contact destinations, or add visitor data to logs or metrics.",
    "Redirect outcomes: the metrics interceptor observes the completed redirect response and records one aggregate outcome of 302, 404, 410, or 5xx plus duration. Unknown and deleted codes share the 404 outcome; codes, IPs, destinations, and tokens are never metric labels.",
    "Management authorization: stats and delete use the existing token validation; missing tokens return 401 without limiter activity; only a supplied token that fails validation records an attempt against the direct peer address. The shared rolling 60-second limiter covers both routes, returns 429 with seconds until the oldest blocking attempt expires, and does not reject a valid token solely because that peer is at the limit.",
    "API request body: the API-only filter counts bytes actually received, including when Content-Length is absent or inaccurate; requests within 16,384 bytes are passed through to existing MVC validation, while larger bodies receive a JSON 413 before controller processing.",
    "Response handling: the security-header filter wraps normal and error responses on the main and management servers. MVC exception handling and servlet error dispatch map failures to stable JSON error codes without returning exception messages, stack traces, or internal details.",
    "Actuator flow: operators query health or metrics on the loopback-only management listener; the public main-port /health endpoint remains separate and unchanged."
  ],
  "impacted": [
    {
      "kind": "modify",
      "path": "url-shortener/pom.xml",
      "reason": "FR14\u2013FR15: add Spring Boot Actuator, which supplies the health and metrics endpoints and Micrometer integration."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/api/ApiExceptionHandler.java",
      "reason": "FR6\u2013FR8: preserve existing error codes, add safe mappings for framework and unexpected errors, and add Retry-After for the database-unavailable response."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/api/LinkController.java",
      "reason": "FR10: count supplied-but-incorrect tokens from the direct peer across stats and delete, without counting missing tokens or rejecting valid tokens."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/api/RedirectController.java",
      "reason": "FR6: map an unavailable database during the required link lookup to 503 service_unavailable with Retry-After: 5, without retrying."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/service/RateLimitedException.java",
      "reason": "FR10: allow the existing 429 response type to carry a management-token-specific message and its calculated Retry-After value."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/resources/application.yml",
      "reason": "FR15\u2013FR16: expose only Actuator health and metrics on a separate management port bound to 127.0.0.1, leaving the main-port /health configuration intact."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/service/ManagementTokenRateLimiter.java",
      "reason": "FR10: maintain a per-direct-peer rolling 60-second window of supplied-but-incorrect management-token attempts across stats and delete."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/api/ApiBodyLimitFilter.java",
      "reason": "FR12: enforce a 16,384-byte limit on actual received /api/** body bytes and return the standard JSON 413 error."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/config/SecurityHeadersFilter.java",
      "reason": "FR13, FR15: apply all four required headers to responses on both the main and management web servers, including errors and Actuator responses."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/api/ApiErrorController.java",
      "reason": "FR8: normalize servlet error dispatches such as unmatched routes to the standard JSON error body without exposing internal details."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/api/RedirectMetricsInterceptor.java",
      "reason": "FR14: measure redirect duration and count 302, 404, 410, and 5xx outcomes without recording codes or splitting 404 causes."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/main/java/com/example/shortener/config/RedirectMetricsConfig.java",
      "reason": "FR14: register redirect metrics only for the redirect handler so metrics do not add database work to the hot path."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/support/IntegrationTest.java",
      "reason": "FR15, NFR4: give the separate management server an ephemeral port in shared integration tests to avoid fixed-port conflicts."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/api/RateLimitTest.java",
      "reason": "FR15, NFR4: give the test's separate management server an ephemeral port while retaining coverage of the existing create limit."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/PersistenceRestartTest.java",
      "reason": "FR15, NFR4: start the management server on an ephemeral port in restart tests so the production listener configuration does not collide."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/ClickPersistenceAndUpgradeTest.java",
      "reason": "FR15, NFR4: use an ephemeral management port in application-start tests while continuing to verify existing migration and data preservation."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/SecurityAndErrorContractTest.java",
      "reason": "FR8, FR13, NFR4: automate security-header and standard JSON error checks, including framework-generated and unexpected errors."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/ApiBodyLimitTest.java",
      "reason": "FR12: verify actual received-byte enforcement at the 16,384-byte boundary, including requests without a reliable declared length."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/ManagementTokenRateLimitTest.java",
      "reason": "FR10: verify the shared rolling limit, missing-token exclusion, direct-peer identity, Retry-After, and continued processing of valid tokens."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/RedirectObservabilityAndFailureTest.java",
      "reason": "FR6, FR14: verify redirect database-lookup failure handling and aggregate outcome/timing metrics without code-level tags."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/ManagementEndpointExposureTest.java",
      "reason": "FR15\u2013FR16: verify loopback management binding, only health and metrics exposure, and the unchanged public /health endpoint."
    }
  ],
  "risks": [
    {
      "detection": "SecurityAndErrorContractTest and ManagementEndpointExposureTest inspect all four exact header values on redirects, errors, public health, and Actuator responses.",
      "mitigation": "Register the header filter for both embedded web servers and set headers before dispatch so error responses inherit them.",
      "risk": "A filter may omit headers on framework error dispatches or the separate Actuator server, leaving some responses without the required browser protections."
    },
    {
      "detection": "ApiBodyLimitTest covers exactly 16,384 bytes, 16,385 bytes, absent/inaccurate length, and an accepted valid request.",
      "mitigation": "Count actual bytes received, stop at limit plus one, and pass an equivalent replayable request body to MVC when within the limit.",
      "risk": "A body-size guard that trusts Content-Length or consumes the servlet stream incorrectly could allow oversized chunked bodies or break otherwise valid JSON requests."
    },
    {
      "detection": "ManagementTokenRateLimitTest exercises missing, incorrect, cross-endpoint, valid-token, retry timing, and spoofed-forwarding-header cases.",
      "mitigation": "Record only after the existing service returns invalid_token, key by HttpServletRequest.getRemoteAddr(), share one limiter, and do not pre-reject requests before token validation.",
      "risk": "The rolling token limiter could count missing tokens, fail to share state across stats and delete, trust spoofed forwarding headers, or block valid tokens."
    },
    {
      "detection": "ManagementTokenRateLimitTest verifies expired attempts no longer block; add a focused cleanup assertion for inactive peer entries.",
      "mitigation": "Prune expired rolling-window entries on access and remove empty peer state; keep the design single-node and in-memory as scoped by FR19.",
      "risk": "Per-IP in-memory limiter state can grow with distinct peers and resets on restart."
    },
    {
      "detection": "LinkCreationTest, LinkLifecycleTest, LinkStatsTest, and SecurityAndErrorContractTest assert status and error-code compatibility.",
      "mitigation": "Keep existing ApiException codes authoritative and map only framework/unexpected exceptions and the specified new failure cases.",
      "risk": "Error translation could accidentally change established 400/409, missing-token, invalid-token, expired-link, or deleted-link contracts."
    },
    {
      "detection": "SecurityAndErrorContractTest injects an unexpected exception and checks the JSON fields while asserting that stack and internal details are absent.",
      "mitigation": "Use fixed messages and stable codes for unexpected errors; do not serialize exception text or stack traces.",
      "risk": "A broad 500 handler or servlet error dispatch could expose implementation details or emit a non-JSON response."
    },
    {
      "detection": "RedirectLatencyTest retains the p99-below-50-ms gate; RedirectObservabilityAndFailureTest checks counts, timings, and absence of code-level dimensions.",
      "mitigation": "Use one interceptor, in-process Micrometer measurements, and only fixed outcome tags; do not include codes or make additional database calls.",
      "risk": "Metrics instrumentation could add work or high-cardinality labels to the latency-sensitive redirect path."
    },
    {
      "detection": "RedirectObservabilityAndFailureTest verifies lookup failure returns 503 and ClickFailureIsolationTest continues to verify recorder failure does not prevent a redirect; confirm this interpretation against FR6 at review.",
      "mitigation": "Apply the 503 mapping to the required link lookup; preserve the existing best-effort click recording behavior and do not retry either operation.",
      "risk": "Mapping database failures to 503 at the wrong point could turn an existing best-effort click-write failure into a failed visitor redirect, contrary to ClickFailureIsolationTest."
    },
    {
      "detection": "ManagementEndpointExposureTest checks the management listener address and endpoint exposure, and verifies the unchanged public /health route.",
      "mitigation": "Bind its separate port to 127.0.0.1 and explicitly expose only health and metrics.",
      "risk": "The configured management listener could become publicly reachable or expose unintended Actuator endpoints."
    },
    {
      "detection": "NoOutboundFetchTest and LinkStatsTest continue to protect no-outbound-fetch and visitor-data behavior; review added logging and run the full suite.",
      "mitigation": "Add no request-, code-, IP-, token-, or destination-specific logs; retain existing redirect and click-recorder behavior without destination checks or outbound calls.",
      "risk": "Changes to error mapping or filters could add visitor-specific logging or destination requests/retries."
    }
  ],
  "test_strategy": [
    "Existing LinkLifecycleTest protects active 302 destination/cache behavior, expired 410, unknown/deleted 404, retention-visible tombstones, and missing/invalid management-token contracts.",
    "Existing LinkCreationTest protects invalid-input 400 and alias-conflict 409 behavior; LinkStatsTest protects stats, token behavior, privacy, and click semantics.",
    "Existing RateLimitTest protects the 20-creates-per-minute limit, Retry-After, direct-peer identity, and ignoring X-Forwarded-For.",
    "Existing ClickFailureIsolationTest and ClickDeletionRaceTest protect best-effort click recording and click/deletion consistency.",
    "Existing RedirectLatencyTest protects the in-process redirect p99 target below 50 ms; NoOutboundFetchTest protects the absence of destination fetches.",
    "Existing HealthTest protects the public /health response; ClickPersistenceAndUpgradeTest and PersistenceRestartTest protect existing records, tombstones, restart behavior, and immutable migration history.",
    "Add SecurityAndErrorContractTest for required headers and JSON errors on success/error responses, including 404, 405, 500, and sanitized unexpected failures.",
    "Add ApiBodyLimitTest for actual-byte enforcement, the 16,384-byte boundary, larger payload rejection, and acceptance of valid bodies at or below the limit.",
    "Add ManagementTokenRateLimitTest for 10 supplied incorrect attempts per direct peer in a shared rolling window across stats/delete, 429 and Retry-After, missing-token exclusion, valid-token processing, and forwarding-header spoofing.",
    "Add RedirectObservabilityAndFailureTest for 302/404/410/5xx counters, redirect timing, aggregate 404 behavior, lookup database outage returning 503 with Retry-After: 5, and no service-side retry.",
    "Add ManagementEndpointExposureTest for loopback-only binding, only health and metrics exposure, required headers, and unchanged main-port /health behavior.",
    "Run the entire existing and new suite, ensure its test count is at least 95, retain the p99 latency gate, and obtain product-owner release approval."
  ]
}
</approved_impact_analysis>

<test_plan>
{
  "test_cases": [
    {
      "check": "Request a pre-existing active link and verify the response is the existing 302 with the same Location and Cache-Control behavior; verify the stored destination is unchanged.",
      "covers": "FR1",
      "id": "TC-FR1-01",
      "level": "integration"
    },
    {
      "check": "Verify existing expired and deleted link records retain their current 410 and 404 behavior across an application restart, and verify no migration changes the existing link or tombstone data.",
      "covers": "FR2",
      "id": "TC-FR2-01",
      "level": "integration"
    },
    {
      "check": "Submit invalid create input and a conflicting alias; verify each returns its existing 400 or 409 status and exact existing error code.",
      "covers": "FR3",
      "id": "TC-FR3-01",
      "level": "integration"
    },
    {
      "check": "Call stats and delete without a token and with an incorrect token below the limit; verify respectively 401/missing_token and 403/invalid_token.",
      "covers": "FR4",
      "id": "TC-FR4-01",
      "level": "integration"
    },
    {
      "check": "Request unknown and deleted codes and an expired link; verify 404/not_found for the first two and 410/expired for the last.",
      "covers": "FR5",
      "id": "TC-FR5-01",
      "level": "integration"
    },
    {
      "check": "Make the database link lookup fail during a redirect; verify 503/service_unavailable, Retry-After: 5, the standard JSON error body, and exactly one lookup attempt.",
      "covers": "FR6",
      "id": "TC-FR6-01",
      "level": "integration"
    },
    {
      "check": "Cause an unexpected server exception; verify 500/internal_error with the standard JSON body and confirm the response contains no exception text, stack trace, or internal details.",
      "covers": "FR7",
      "id": "TC-FR7-01",
      "level": "integration"
    },
    {
      "check": "Exercise application and framework errors, including unmatched route, unsupported method, oversized body, and unexpected exception; verify each has application/json and exactly the error and message fields with its specified status/code pair.",
      "covers": "FR8",
      "id": "TC-FR8-01",
      "level": "integration"
    },
    {
      "check": "From one direct peer IP, create 20 links within a minute and verify they are admitted; verify the next create returns 429/rate_limited with a Retry-After header.",
      "covers": "FR9",
      "id": "TC-FR9-01",
      "level": "integration"
    },
    {
      "check": "With a controlled clock, verify the limiter admits 10 supplied incorrect attempts per peer in a rolling 60-second window, blocks the next incorrect attempt with a positive delta-seconds retry time, and admits an attempt after the oldest blocking entry expires.",
      "covers": "FR10",
      "id": "TC-FR10-01",
      "level": "unit"
    },
    {
      "check": "Make 10 incorrect-token requests distributed across stats and delete from one direct peer; verify the next incorrect request to either route returns 429/rate_limited with Retry-After. Verify missing-token requests return 401 without consuming attempts, a valid token is still processed at the limit, and spoofed forwarding headers do not change the peer identity.",
      "covers": "FR10",
      "id": "TC-FR10-02",
      "level": "integration"
    },
    {
      "check": "Issue a sequence of unknown and deleted-code redirects from one peer; verify none is rate-limited and their metrics share one aggregate 404 outcome with no code or cause dimension.",
      "covers": "FR11",
      "id": "TC-FR11-01",
      "level": "integration"
    },
    {
      "check": "Send /api/** bodies of exactly 16,384 and 16,385 actual bytes; verify the boundary-sized request is not rejected for size and the larger request returns 413/payload_too_large with the standard JSON body. Repeat with absent or inaccurate Content-Length to verify enforcement uses received bytes.",
      "covers": "FR12",
      "id": "TC-FR12-01",
      "level": "integration"
    },
    {
      "check": "Inspect representative success, redirect, error, public health, and Actuator responses; verify all include X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: no-referrer, and Content-Security-Policy: default-src 'none'; frame-ancestors 'none'.",
      "covers": "FR13",
      "id": "TC-FR13-01",
      "level": "integration"
    },
    {
      "check": "Generate redirect outcomes 302, 404, 410, and 5xx, then query local Actuator metrics; verify each outcome count and redirect timing are observable, and unknown/deleted 404s are aggregated without code- or cause-specific labels.",
      "covers": "FR14",
      "id": "TC-FR14-01",
      "level": "integration"
    },
    {
      "check": "Verify the management listener is bound to 127.0.0.1 on its separate port, health and metrics are reachable locally, no other Actuator endpoint is exposed, and a request through the public listener cannot reach Actuator.",
      "covers": "FR15",
      "id": "TC-FR15-01",
      "level": "integration"
    },
    {
      "check": "Request /health on the main port and verify its existing status and response body are unchanged.",
      "covers": "FR16",
      "id": "TC-FR16-01",
      "level": "integration"
    },
    {
      "check": "Exercise successful and failed visitor redirects, then inspect captured application logs; verify the change emits no visitor-specific code, IP, destination, or request logging.",
      "covers": "FR17",
      "id": "TC-FR17-01",
      "level": "integration"
    },
    {
      "check": "Redirect to a destination served by a recording test server and verify no outbound request is made; verify redirect handling performs no destination retry or reputation/malware lookup and introduces no authentication requirement beyond the existing management token.",
      "covers": "FR18",
      "id": "TC-FR18-01",
      "level": "integration"
    },
    {
      "check": "Review the change manifest and build artifacts; verify changes are confined to the url-shortener service and introduce no infrastructure, deployment, or third-party integration changes.",
      "covers": "FR19",
      "id": "TC-FR19-01",
      "level": "unit"
    },
    {
      "check": "With the service and database available, request active links repeatedly and verify every response is the expected successful redirect and none is 5xx.",
      "covers": "NFR1",
      "id": "TC-NFR1-01",
      "level": "integration"
    },
    {
      "check": "Run the existing in-process redirect latency check and verify the measured p99 is below 50 ms.",
      "covers": "NFR2",
      "id": "TC-NFR2-01",
      "level": "integration"
    },
    {
      "check": "Capture logs while exercising visitor requests and verify no new visitor-specific log entries or fields are emitted.",
      "covers": "NFR3",
      "id": "TC-NFR3-01",
      "level": "integration"
    },
    {
      "check": "Run the complete existing and new automated test suite; verify all tests pass, the reported suite count is at least 95, and automated tests exercise the required security headers and error behavior.",
      "covers": "NFR4",
      "id": "TC-NFR4-01",
      "level": "integration"
    }
  ]
}
</test_plan>

<implementation_and_existing_tests>
<file path="url-shortener/pom.xml">
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.4.5</version>
        <relativePath/>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>url-shortener</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <name>url-shortener</name>
    <description>URL shortener service: short links, redirects, expiry, token-authorized deletion</description>

    <properties>
        <java.version>17</java.version>
        <bucket4j.version>8.14.0</bucket4j.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-validation</artifactId>
        </dependency>
        <dependency>
            <!-- health and metrics on a loopback-only management port (FR14, FR15) -->
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.flywaydb</groupId>
            <artifactId>flyway-core</artifactId>
        </dependency>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>com.bucket4j</groupId>
            <artifactId>bucket4j_jdk17-core</artifactId>
            <version>${bucket4j.version}</version>
        </dependency>

        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
</file>

<file path="url-shortener/src/main/java/com/example/shortener/ShortenerApplication.java">
package com.example.shortener;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class ShortenerApplication {

    public static void main(String[] args) {
        SpringApplication.run(ShortenerApplication.class, args);
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/ApiErrorController.java">
package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;
import jakarta.servlet.RequestDispatcher;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.web.servlet.error.ErrorController;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Replaces Spring Boot's default /error page, used when an error happens outside MVC (for example in
 * a filter or the servlet container), so those responses also use the standard body (FR8).
 */
@RestController
public class ApiErrorController implements ErrorController {

    @RequestMapping("${server.error.path:/error}")
    public ResponseEntity<ErrorResponse> error(HttpServletRequest request) {
        Object code = request.getAttribute(RequestDispatcher.ERROR_STATUS_CODE);
        int status = code instanceof Integer i ? i : 500;
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(ErrorBodies.forStatus(status));
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/ApiExceptionHandler.java">
package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;
import com.example.shortener.service.ApiException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Every error is JSON {"error": <stable code>, "message": <human text>} (FR8). The service's own
 * ApiException codes are authoritative and unchanged; only framework and unexpected errors are
 * translated here, and never with internal details (FR7, FR16).
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ApiException.class)
    ResponseEntity<ErrorResponse> api(ApiException e) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(e.getStatus()).contentType(MediaType.APPLICATION_JSON);
        if (e.getRetryAfterSeconds() != null) {
            response.header(HttpHeaders.RETRY_AFTER, Long.toString(e.getRetryAfterSeconds()));
        }
        return response.body(new ErrorResponse(e.getError(), e.getMessage()));
    }

    /** Malformed JSON, or a field of the wrong type such as an unparseable expiresAt. */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ErrorResponse> unreadable(HttpMessageNotReadableException e) {
        return body(HttpStatus.BAD_REQUEST, "invalid_request", "request body is not valid JSON for this endpoint");
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<ErrorResponse> mediaType(HttpMediaTypeNotSupportedException e) {
        return body(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "use Content-Type: application/json");
    }

    /**
     * Everything else. Spring MVC's own errors (unmatched route, wrong method, ...) carry their status
     * and headers (such as Allow), which are kept with our body; anything unexpected becomes a 500 with a
     * fixed message, so no exception text or stack trace ever reaches a client.
     */
    @ExceptionHandler(Exception.class)
    ResponseEntity<ErrorResponse> other(Exception e) {
        if (e instanceof org.springframework.web.ErrorResponse framework) {
            HttpStatusCode status = framework.getStatusCode();
            return ResponseEntity.status(status).headers(framework.getHeaders()).contentType(MediaType.APPLICATION_JSON)
                    .body(ErrorBodies.forStatus(status.value()));
        }
        return body(HttpStatus.INTERNAL_SERVER_ERROR, "internal_error", "an unexpected error occurred");
    }

    private static ResponseEntity<ErrorResponse> body(HttpStatus status, String error, String message) {
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(new ErrorResponse(error, message));
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/ErrorBodies.java">
package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;

/** Standard bodies for errors that arrive as a bare status (framework errors, servlet error dispatch). */
final class ErrorBodies {

    private ErrorBodies() {
    }

    static ErrorResponse forStatus(int status) {
        return switch (status) {
            case 400 -> new ErrorResponse("invalid_request", "the request is not valid");
            case 404 -> new ErrorResponse("not_found", "no such resource");
            case 405 -> new ErrorResponse("method_not_allowed", "this method is not allowed here");
            case 413 -> new ErrorResponse("payload_too_large", "the request body is too large");
            case 415 -> new ErrorResponse("unsupported_media_type", "use Content-Type: application/json");
            case 503 -> new ErrorResponse("service_unavailable", "the service is temporarily unavailable; retry later");
            default -> status >= 500
                    ? new ErrorResponse("internal_error", "an unexpected error occurred")
                    : new ErrorResponse("invalid_request", "the request could not be processed");
        };
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/HealthController.java">
package com.example.shortener.api;

import java.util.Map;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** 200 when the service can reach its H2 store, 503 otherwise (FR6). */
@RestController
public class HealthController {

    private final JdbcTemplate jdbc;

    public HealthController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        try {
            jdbc.queryForObject("SELECT 1", Integer.class);
            return ResponseEntity.ok(Map.of("status", "UP"));
        } catch (DataAccessException e) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of("status", "DOWN"));
        }
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/LinkController.java">
package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.api.LinkDtos.CreateLinkRequest;
import com.example.shortener.api.LinkDtos.CreateLinkResponse;
import com.example.shortener.api.LinkDtos.LinkMetadata;
import com.example.shortener.api.LinkDtos.StatsResponse;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.ManagementTokenRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.CreatedLink;
import jakarta.servlet.http.HttpServletRequest;
import java.util.function.Supplier;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/links")
public class LinkController {

    static final String TOKEN_HEADER = "X-Management-Token";

    private final LinkService links;
    private final CreateRateLimiter rateLimiter;
    private final ManagementTokenRateLimiter tokenLimiter;

    public LinkController(LinkService links, CreateRateLimiter rateLimiter, ManagementTokenRateLimiter tokenLimiter) {
        this.links = links;
        this.rateLimiter = rateLimiter;
        this.tokenLimiter = tokenLimiter;
    }

    @PostMapping
    public ResponseEntity<CreateLinkResponse> create(@RequestBody CreateLinkRequest request, HttpServletRequest http) {
        if (request == null) {
            throw ApiException.badRequest("invalid_request", "request body is required");
        }
        // The network peer address: forwarding headers are client-controlled and not trusted.
        rateLimiter.acquire(http.getRemoteAddr());
        CreatedLink created = links.create(request.url(), request.alias(), request.expiresAt());
        String code = created.link().getCode();
        return ResponseEntity.created(URI.create("/api/links/" + code))
                .body(new CreateLinkResponse(code, "/" + code, created.managementToken()));
    }

    @GetMapping("/{code}")
    public LinkMetadata metadata(@PathVariable String code) {
        return LinkMetadata.of(links.metadata(code));
    }

    @GetMapping("/{code}/stats")
    public StatsResponse stats(@PathVariable String code,
                               @RequestHeader(name = TOKEN_HEADER, required = false) String token,
                               HttpServletRequest http) {
        return StatsResponse.of(withTokenThrottle(http, () -> links.stats(code, token)));
    }

    @DeleteMapping("/{code}")
    public ResponseEntity<Void> delete(@PathVariable String code,
                                       @RequestHeader(name = TOKEN_HEADER, required = false) String token,
                                       HttpServletRequest http) {
        withTokenThrottle(http, () -> {
            links.delete(code, token);
            return null;
        });
        return ResponseEntity.noContent().build();
    }

    /**
     * Runs a token-protected operation. A wrong token is counted against the caller's peer address and
     * stays 403 invalid_token until the limit is exceeded, then becomes 429 (FR10). Valid and missing
     * tokens are untouched: the existing contract decides those.
     */
    private <T> T withTokenThrottle(HttpServletRequest http, Supplier<T> operation) {
        try {
            return operation.get();
        } catch (ApiException e) {
            if ("invalid_token".equals(e.getError())) {
                tokenLimiter.recordFailure(http.getRemoteAddr());
            }
            throw e;
        }
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/LinkDtos.java">
package com.example.shortener.api;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import com.example.shortener.domain.Link;
import com.example.shortener.service.LinkService.LinkStats;

/** Request and response bodies of the /api/links resource. */
public final class LinkDtos {

    private LinkDtos() {
    }

    /** {@code alias} and {@code expiresAt} (ISO-8601 instant) are optional. */
    public record CreateLinkRequest(String url, String alias, Instant expiresAt) {
    }

    public record CreateLinkResponse(String code, String shortPath, String managementToken) {
    }

    /** Public metadata. {@code alias} is set only for links created with a custom alias. */
    public record LinkMetadata(String code, String alias, String originalUrl, Instant createdAt, Instant expiresAt) {

        static LinkMetadata of(Link link) {
            return new LinkMetadata(link.getCode(), link.isCustomAlias() ? link.getCode() : null,
                    link.getOriginalUrl(), link.getCreatedAt(), link.getExpiresAt());
        }
    }

    /** Click counts only: no unique-visitor or other per-visitor metric (FR5). */
    public record StatsResponse(long totalClicks, List<DailyClicksResponse> dailyClicks, Instant lastClickedAt) {

        static StatsResponse of(LinkStats stats) {
            return new StatsResponse(stats.totalClicks(),
                    stats.dailyClicks().stream().map(d -> new DailyClicksResponse(d.date(), d.clicks())).toList(),
                    stats.lastClickedAt());
        }
    }

    public record DailyClicksResponse(LocalDate date, long clicks) {
    }

    public record ErrorResponse(String error, String message) {
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/RedirectController.java">
package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.Redirect;
import com.example.shortener.service.ServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** The latency-sensitive path: one indexed lookup, a best-effort click insert, then a 302. */
@RestController
public class RedirectController {

    private static final Logger log = LoggerFactory.getLogger(RedirectController.class);

    private final LinkService links;
    private final ClickRecorder clicks;

    public RedirectController(LinkService links, ClickRecorder clicks) {
        this.links = links;
        this.clicks = clicks;
    }

    // Literal routes (/health, /api/...) take precedence over this pattern in Spring MVC.
    @GetMapping("/{code:[A-Za-z0-9_-]{3,32}}")
    public ResponseEntity<Void> redirect(@PathVariable String code) {
        Redirect redirect;
        try {
            redirect = links.resolve(code);
        } catch (DataAccessResourceFailureException | TransientDataAccessException | CannotCreateTransactionException e) {
            // The link store cannot answer: say so with 503 + Retry-After instead of an opaque 500 (FR6).
            throw new ServiceUnavailableException();
        }
        URI destination = URI.create(redirect.destination());
        try {
            clicks.record(redirect.linkId());
        } catch (RuntimeException e) {
            // Redirecting is the product; analytics are best-effort (NFR1). The click is lost, not the visit.
            log.warn("click not recorded: {}", e.getClass().getSimpleName());
        }
        // no-store: links can expire or be deleted, so no client or proxy may cache the redirect
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(destination)
                .cacheControl(CacheControl.noStore())
                .build();
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/RedirectMetricsInterceptor.java">
package com.example.shortener.api;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Redirect observability (FR14): one timer, shortener.redirects, tagged only with the outcome
 * (302, 404, 410, 5xx; anything else is "other"). Its count is the per-outcome count and its timing the
 * redirect latency. No code, destination or client tags, and no extra work on the hot path.
 */
@Component
public class RedirectMetricsInterceptor implements HandlerInterceptor {

    static final String METRIC = "shortener.redirects";
    private static final String STARTED = RedirectMetricsInterceptor.class.getName() + ".started";

    private final MeterRegistry registry;
    private final Map<String, Timer> timers = new ConcurrentHashMap<>();

    public RedirectMetricsInterceptor(MeterRegistry registry) {
        this.registry = registry;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (isRedirect(handler)) {
            request.setAttribute(STARTED, System.nanoTime());
        }
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        if (request.getAttribute(STARTED) instanceof Long started) {
            String outcome = outcome(response.getStatus());
            timers.computeIfAbsent(outcome, o -> Timer.builder(METRIC).tag("outcome", o)
                            .description("Redirect requests by outcome").register(registry))
                    .record(System.nanoTime() - started, TimeUnit.NANOSECONDS);
        }
    }

    static String outcome(int status) {
        return switch (status) {
            case 302 -> "302";
            case 404 -> "404";
            case 410 -> "410";
            default -> status >= 500 ? "5xx" : "other";
        };
    }

    private static boolean isRedirect(Object handler) {
        return handler instanceof HandlerMethod method && method.getBeanType() == RedirectController.class;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/ApiBodyLimitFilter.java">
package com.example.shortener.config;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.api.LinkDtos.ErrorResponse;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Rejects /api/** request bodies larger than the limit with 413 payload_too_large (FR12). It counts the
 * bytes actually received (stopping at limit + 1), so a missing or false Content-Length cannot bypass
 * it, then hands the buffered body on unchanged.
 */
public class ApiBodyLimitFilter extends OncePerRequestFilter {

    private final int maxBytes;
    private final ObjectMapper json;

    public ApiBodyLimitFilter(int maxBytes, ObjectMapper json) {
        this.maxBytes = maxBytes;
        this.json = json;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI().substring(request.getContextPath().length());
        return !(path.equals("/api") || path.startsWith("/api/"));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if (request.getContentLengthLong() > maxBytes) {
            reject(response);
            return;
        }
        byte[] body = readAtMost(request.getInputStream(), maxBytes + 1);
        if (body.length > maxBytes) {
            reject(response);
            return;
        }
        chain.doFilter(new BufferedBodyRequest(request, body), response);
    }

    private void reject(HttpServletResponse response) throws IOException {
        response.setStatus(HttpServletResponse.SC_REQUEST_ENTITY_TOO_LARGE);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        json.writeValue(response.getOutputStream(), new ErrorResponse("payload_too_large",
                "the request body must be at most " + maxBytes + " bytes"));
    }

    private static byte[] readAtMost(InputStream in, int limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(Math.min(limit, 8192));
        byte[] chunk = new byte[8192];
        int read;
        while (out.size() < limit && (read = in.read(chunk, 0, Math.min(chunk.length, limit - out.size()))) != -1) {
            out.write(chunk, 0, read);
        }
        return out.toByteArray();
    }

    private static final class BufferedBodyRequest extends HttpServletRequestWrapper {

        private final byte[] body;

        BufferedBodyRequest(HttpServletRequest request, byte[] body) {
            super(request);
            this.body = body;
        }

        @Override
        public ServletInputStream getInputStream() {
            ByteArrayInputStream in = new ByteArrayInputStream(body);
            return new ServletInputStream() {
                @Override
                public int read() {
                    return in.read();
                }

                @Override
                public int read(byte[] b, int off, int len) {
                    return in.read(b, off, len);
                }

                @Override
                public boolean isFinished() {
                    return in.available() == 0;
                }

                @Override
                public boolean isReady() {
                    return true;
                }

                @Override
                public void setReadListener(ReadListener listener) {
                    throw new UnsupportedOperationException("synchronous body only");
                }
            };
        }

        @Override
        public int getContentLength() {
            return body.length;
        }

        @Override
        public long getContentLengthLong() {
            return body.length;
        }
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/AppConfig.java">
package com.example.shortener.config;

import java.net.InetAddress;
import java.security.SecureRandom;
import java.time.Clock;

import com.example.shortener.service.HostResolver;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Time, randomness and DNS are injectable seams so behaviour is deterministic under test. */
@Configuration
public class AppConfig {

    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }

    @Bean
    SecureRandom secureRandom() {
        return new SecureRandom();
    }

    @Bean
    HostResolver hostResolver() {
        return InetAddress::getAllByName;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/ManagementSecurityHeadersConfig.java">
package com.example.shortener.config;

import org.springframework.boot.actuate.autoconfigure.web.ManagementContextConfiguration;
import org.springframework.boot.actuate.autoconfigure.web.ManagementContextType;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.core.Ordered;

/**
 * The management server is a separate child context with its own filters, so the security headers
 * are registered there too (FR13 applies to every response). Listed in
 * META-INF/spring/...ManagementContextConfiguration.imports.
 */
@ManagementContextConfiguration(value = ManagementContextType.CHILD, proxyBeanMethods = false)
public class ManagementSecurityHeadersConfig {

    @Bean
    FilterRegistrationBean<SecurityHeadersFilter> managementSecurityHeadersFilter() {
        FilterRegistrationBean<SecurityHeadersFilter> registration = new FilterRegistrationBean<>(new SecurityHeadersFilter());
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return registration;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/SecurityHeadersFilter.java">
package com.example.shortener.config;

import java.io.IOException;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Browser-side hardening on every response (FR13), set before the request is handled so redirects,
 * errors and error dispatches all carry them.
 */
public class SecurityHeadersFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        response.setHeader("X-Content-Type-Options", "nosniff");
        response.setHeader("X-Frame-Options", "DENY");
        response.setHeader("Referrer-Policy", "no-referrer");
        response.setHeader("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
        chain.doFilter(request, response);
    }

    @Override
    protected boolean shouldNotFilterErrorDispatch() {
        return false; // error responses need the headers too
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/ShortenerProperties.java">
package com.example.shortener.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param dataDir         directory holding the file-based H2 database
 * @param rateLimit       per-client-IP limits
 * @param codeLength      length of generated short codes
 * @param maxApiBodyBytes largest request body accepted on /api/**
 */
@ConfigurationProperties(prefix = "shortener")
public record ShortenerProperties(String dataDir, RateLimit rateLimit, int codeLength, int maxApiBodyBytes) {

    /**
     * @param createsPerMinute             link creations per client IP per minute
     * @param failedTokenAttemptsPerMinute wrong management tokens per client IP per rolling minute
     */
    public record RateLimit(int createsPerMinute, int failedTokenAttemptsPerMinute) {
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/config/WebConfig.java">
package com.example.shortener.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.api.RedirectMetricsInterceptor;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** Filters and interceptors for the public web server. */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final RedirectMetricsInterceptor redirectMetrics;

    public WebConfig(RedirectMetricsInterceptor redirectMetrics) {
        this.redirectMetrics = redirectMetrics;
    }

    @Bean
    FilterRegistrationBean<SecurityHeadersFilter> securityHeadersFilter() {
        FilterRegistrationBean<SecurityHeadersFilter> registration = new FilterRegistrationBean<>(new SecurityHeadersFilter());
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE); // first, so even rejected requests carry the headers
        return registration;
    }

    @Bean
    FilterRegistrationBean<ApiBodyLimitFilter> apiBodyLimitFilter(ShortenerProperties properties, ObjectMapper json) {
        FilterRegistrationBean<ApiBodyLimitFilter> registration =
                new FilterRegistrationBean<>(new ApiBodyLimitFilter(properties.maxApiBodyBytes(), json));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
        return registration;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(redirectMetrics); // it ignores every handler except the redirect
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/domain/ClickEvent.java">
package com.example.shortener.domain;

import java.time.Instant;
import java.time.LocalDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One successful redirect. Deliberately holds no visitor data (no IP address, user agent,
 * cookie or fingerprint): only which link, when, and the UTC day used for daily counts.
 */
@Entity
@Table(name = "click_events")
public class ClickEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "link_id", nullable = false)
    private Long linkId;

    @Column(name = "clicked_at", nullable = false)
    private Instant clickedAt;

    /** Stored, not derived at query time, so daily grouping never depends on a session time zone. */
    @Column(name = "click_date", nullable = false)
    private LocalDate clickDate;

    protected ClickEvent() {
    }

    public ClickEvent(Long linkId, Instant clickedAt, LocalDate clickDate) {
        this.linkId = linkId;
        this.clickedAt = clickedAt;
        this.clickDate = clickDate;
    }

    public Long getLinkId() {
        return linkId;
    }

    public Instant getClickedAt() {
        return clickedAt;
    }

    public LocalDate getClickDate() {
        return clickDate;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/domain/ClickEventRepository.java">
package com.example.shortener.domain;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ClickEventRepository extends JpaRepository<ClickEvent, Long> {

    long countByLinkId(Long linkId);

    @Query("select max(c.clickedAt) from ClickEvent c where c.linkId = :linkId")
    Instant findLastClickedAt(@Param("linkId") Long linkId);

    /** Days with at least one click from {@code from} onward; the caller fills in the empty days. */
    @Query("select c.clickDate as day, count(c) as clicks from ClickEvent c "
            + "where c.linkId = :linkId and c.clickDate >= :from group by c.clickDate")
    List<DailyCount> countPerDaySince(@Param("linkId") Long linkId, @Param("from") LocalDate from);

    @Modifying
    @Query("delete from ClickEvent c where c.linkId = :linkId")
    int deleteByLinkId(@Param("linkId") Long linkId);

    interface DailyCount {
        LocalDate getDay();

        long getClicks();
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/domain/Link.java">
package com.example.shortener.domain;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A short link. Deletion turns it into a tombstone: the row stays so its code is reserved
 * forever, while the destination URL and token hash are erased.
 */
@Entity
@Table(name = "links")
public class Link {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 32)
    private String code;

    @Column(name = "original_url", length = 2048)
    private String originalUrl;

    @Column(name = "custom_alias", nullable = false)
    private boolean customAlias;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at")
    private Instant expiresAt;

    @Column(name = "token_hash", length = 64)
    private String tokenHash;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    protected Link() {
    }

    public Link(String code, String originalUrl, boolean customAlias, Instant createdAt, Instant expiresAt,
                String tokenHash) {
        this.code = code;
        this.originalUrl = originalUrl;
        this.customAlias = customAlias;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
        this.tokenHash = tokenHash;
    }

    public boolean isDeleted() {
        return deletedAt != null;
    }

    /** Expired at or after the expiry instant (FR2). */
    public boolean isExpiredAt(Instant now) {
        return expiresAt != null && !now.isBefore(expiresAt);
    }

    public void markDeleted(Instant now) {
        this.deletedAt = now;
        this.originalUrl = null;
        this.tokenHash = null;
    }

    public Long getId() {
        return id;
    }

    public String getCode() {
        return code;
    }

    public String getOriginalUrl() {
        return originalUrl;
    }

    public boolean isCustomAlias() {
        return customAlias;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public String getTokenHash() {
        return tokenHash;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/domain/LinkRepository.java">
package com.example.shortener.domain;

import java.util.Optional;

import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface LinkRepository extends JpaRepository<Link, Long> {

    /** Includes tombstones: a deleted code is still "taken". */
    Optional<Link> findByCode(String code);

    boolean existsByCode(String code);

    /**
     * Reads the link under a row lock (SELECT ... FOR UPDATE) for the rest of the transaction.
     * Click recording and deletion both take it, so a click can never be committed after the
     * deletion that erased the link's clicks.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select l from Link l where l.id = :id")
    Optional<Link> lockById(@Param("id") Long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select l from Link l where l.code = :code")
    Optional<Link> lockByCode(@Param("code") String code);
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/AliasPolicy.java">
package com.example.shortener.service;

import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

/** Custom alias rules: 3-32 characters from [A-Za-z0-9_-], case-sensitive, not a reserved path. */
@Component
public class AliasPolicy {

    private static final Pattern ALIAS = Pattern.compile("[A-Za-z0-9_-]{3,32}");

    /** Top-level paths the service itself uses. Checked case-insensitively so "API" can't shadow "api". */
    static final Set<String> RESERVED = Set.of("api", "health", "links", "error", "actuator");

    public void validate(String alias) {
        if (!ALIAS.matcher(alias).matches()) {
            throw ApiException.badRequest("invalid_alias",
                    "alias must be 3-32 characters from letters, digits, '_' and '-'");
        }
        if (isReserved(alias)) {
            throw ApiException.badRequest("reserved_alias", "alias '" + alias + "' is reserved");
        }
    }

    public boolean isReserved(String code) {
        return RESERVED.contains(code.toLowerCase(Locale.ROOT));
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/ApiException.java">
package com.example.shortener.service;

import org.springframework.http.HttpStatus;

/** A request failure with a stable machine-readable error code and an HTTP status. */
public class ApiException extends RuntimeException {

    private final HttpStatus status;
    private final String error;
    private final Long retryAfterSeconds; // sent as Retry-After when set

    public ApiException(HttpStatus status, String error, String message) {
        this(status, error, message, null);
    }

    public ApiException(HttpStatus status, String error, String message, Long retryAfterSeconds) {
        super(message);
        this.status = status;
        this.error = error;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public static ApiException badRequest(String error, String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, error, message);
    }

    public static ApiException notFound() {
        return new ApiException(HttpStatus.NOT_FOUND, "not_found", "no such link");
    }

    public HttpStatus getStatus() {
        return status;
    }

    public String getError() {
        return error;
    }

    public Long getRetryAfterSeconds() {
        return retryAfterSeconds;
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/ClickRecorder.java">
package com.example.shortener.service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;

import com.example.shortener.domain.ClickEvent;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.domain.LinkRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Records a click in its own short transaction, separate from the redirect lookup, so the
 * caller can contain any failure (NFR1). The link row is locked while recording, the same lock
 * deletion takes, so a click is never committed after its link's clicks were erased (FR3).
 */
@Service
public class ClickRecorder {

    private final LinkRepository links;
    private final ClickEventRepository clicks;
    private final Clock clock;

    public ClickRecorder(LinkRepository links, ClickEventRepository clicks, Clock clock) {
        this.links = links;
        this.clicks = clicks;
        this.clock = clock;
    }

    @Transactional
    public void record(Long linkId) {
        links.lockById(linkId).filter(link -> !link.isDeleted()).ifPresent(link -> {
            Instant now = clock.instant().truncatedTo(ChronoUnit.MICROS);
            clicks.save(new ClickEvent(linkId, now, LocalDate.ofInstant(now, ZoneOffset.UTC)));
        });
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/CodeGenerator.java">
package com.example.shortener.service;

import java.security.SecureRandom;

import com.example.shortener.config.ShortenerProperties;
import org.springframework.stereotype.Component;

/** Cryptographically random short codes from the URL-safe alphabet [A-Za-z0-9_-]. */
@Component
public class CodeGenerator {

    private static final char[] ALPHABET =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-".toCharArray();

    private final SecureRandom random;
    private final int length;

    public CodeGenerator(SecureRandom random, ShortenerProperties properties) {
        this.random = random;
        this.length = properties.codeLength();
    }

    public String next() {
        char[] code = new char[length];
        for (int i = 0; i < length; i++) {
            code[i] = ALPHABET[random.nextInt(ALPHABET.length)];
        }
        return new String(code);
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/CreateRateLimiter.java">
package com.example.shortener.service;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.TimeUnit;

import com.example.shortener.config.ShortenerProperties;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.ConsumptionProbe;
import org.springframework.stereotype.Component;

/**
 * In-memory per-client-IP limit on link creation (NFR3): N creates per minute, refilled once a
 * minute. State is lost on restart by design. One bucket is kept per distinct client address;
 * that is fine for a single-node service but would need eviction or a shared store at scale.
 */
@Component
public class CreateRateLimiter {

    private final ConcurrentMap<String, Bucket> buckets = new ConcurrentHashMap<>();
    private final int perMinute;

    public CreateRateLimiter(ShortenerProperties properties) {
        this.perMinute = properties.rateLimit().createsPerMinute();
    }

    /** Consumes one create for this client, or throws 429 with a Retry-After in seconds. */
    public void acquire(String clientAddress) {
        ConsumptionProbe probe = buckets.computeIfAbsent(clientAddress, k -> newBucket()).tryConsumeAndReturnRemaining(1);
        if (!probe.isConsumed()) {
            long seconds = Math.max(1, TimeUnit.NANOSECONDS.toSeconds(probe.getNanosToWaitForRefill() + 999_999_999L));
            throw new RateLimitedException(seconds);
        }
    }

    private Bucket newBucket() {
        Bandwidth limit = Bandwidth.builder()
                .capacity(perMinute)
                .refillIntervally(perMinute, Duration.ofMinutes(1))
                .build();
        return Bucket.builder().addLimit(limit).build();
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/DestinationPolicy.java">
package com.example.shortener.service;

import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.UnknownHostException;
import java.util.Locale;

import org.springframework.stereotype.Component;

/**
 * Decides which destination URLs may be shortened (NFR2): http/https only, at most 2048
 * characters, and never a host that is, or resolves to, a loopback, private, link-local,
 * unique-local, multicast or unspecified address. DNS is checked once, at creation, and fails
 * closed. The service never fetches destinations, so later DNS changes are an accepted limitation.
 */
@Component
public class DestinationPolicy {

    static final int MAX_URL_LENGTH = 2048;

    private final HostResolver resolver;

    public DestinationPolicy(HostResolver resolver) {
        this.resolver = resolver;
    }

    /** Returns the URL unchanged if acceptable; throws a 400 {@link ApiException} otherwise. */
    public String validate(String url) {
        if (url == null || url.isBlank()) {
            throw invalid("url is required");
        }
        if (url.length() > MAX_URL_LENGTH) {
            throw invalid("url must be at most " + MAX_URL_LENGTH + " characters");
        }
        URI uri;
        try {
            uri = new URI(url);
        } catch (URISyntaxException e) {
            throw invalid("url is not a valid URI");
        }
        String scheme = uri.getScheme();
        if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
            throw invalid("only http and https URLs are allowed");
        }
        String host = uri.getHost();
        if (host == null || host.isBlank()) {
            throw invalid("url must include a host");
        }
        host = stripBrackets(host).toLowerCase(Locale.ROOT);
        if (host.equals("localhost") || host.endsWith(".localhost")) {
            throw prohibited();
        }

        InetAddress[] addresses;
        try {
            addresses = resolver.resolve(host);
        } catch (UnknownHostException | SecurityException e) {
            throw invalid("url host could not be resolved");
        }
        if (addresses == null || addresses.length == 0) {
            throw invalid("url host could not be resolved");
        }
        for (InetAddress address : addresses) {
            if (isProhibited(address)) {
                throw prohibited();
            }
        }
        return url;
    }

    static boolean isProhibited(InetAddress address) {
        if (address.isLoopbackAddress() || address.isAnyLocalAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) {
            return true;
        }
        byte[] raw = address.getAddress();
        if (address instanceof Inet6Address) {
            // fc00::/7 unique-local (Java's isSiteLocalAddress only covers the deprecated fec0::/10)
            return (raw[0] & 0xfe) == 0xfc;
        }
        return false;
    }

    private static String stripBrackets(String host) {
        return host.startsWith("[") && host.endsWith("]") ? host.substring(1, host.length() - 1) : host;
    }

    private static ApiException invalid(String message) {
        return ApiException.badRequest("invalid_url", message);
    }

    private static ApiException prohibited() {
        return ApiException.badRequest("prohibited_destination",
                "url points to a local, private or otherwise prohibited address");
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/HostResolver.java">
package com.example.shortener.service;

import java.net.InetAddress;
import java.net.UnknownHostException;

/** DNS lookup seam: production uses the system resolver; tests substitute fixed answers. */
@FunctionalInterface
public interface HostResolver {

    InetAddress[] resolve(String host) throws UnknownHostException;
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/LinkService.java">
package com.example.shortener.service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.domain.ClickEventRepository.DailyCount;
import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Link lifecycle: create, resolve for redirect, read metadata and stats, delete into a tombstone. */
@Service
public class LinkService {

    static final int MAX_CODE_ATTEMPTS = 10;
    static final int STATS_DAYS = 30;

    private final LinkRepository repository;
    private final DestinationPolicy destinationPolicy;
    private final AliasPolicy aliasPolicy;
    private final CodeGenerator codeGenerator;
    private final TokenService tokenService;
    private final ClickEventRepository clicks;
    private final Clock clock;

    public LinkService(LinkRepository repository, DestinationPolicy destinationPolicy, AliasPolicy aliasPolicy,
                       CodeGenerator codeGenerator, TokenService tokenService, ClickEventRepository clicks,
                       Clock clock) {
        this.repository = repository;
        this.destinationPolicy = destinationPolicy;
        this.aliasPolicy = aliasPolicy;
        this.codeGenerator = codeGenerator;
        this.tokenService = tokenService;
        this.clicks = clicks;
        this.clock = clock;
    }

    /** The plaintext management token is returned here and nowhere else. */
    public record CreatedLink(Link link, String managementToken) {
    }

    /** What a redirect needs: where to send the visitor, and which link to count the click for. */
    public record Redirect(Long linkId, String destination) {
    }

    public record DailyClicks(LocalDate date, long clicks) {
    }

    public record LinkStats(long totalClicks, List<DailyClicks> dailyClicks, Instant lastClickedAt) {
    }

    @Transactional
    public CreatedLink create(String url, String alias, Instant expiresAt) {
        destinationPolicy.validate(url);
        Instant now = now();
        Instant expiry = expiresAt == null ? null : expiresAt.truncatedTo(ChronoUnit.MICROS);
        if (expiry != null && !expiry.isAfter(now)) {
            throw ApiException.badRequest("invalid_expiry", "expiresAt must be in the future");
        }

        String code;
        if (alias != null) {
            aliasPolicy.validate(alias);
            if (repository.existsByCode(alias)) {
                throw aliasTaken();
            }
            code = alias;
        } else {
            code = freshCode();
        }

        String token = tokenService.newToken();
        Link link = new Link(code, url, alias != null, now, expiry, tokenService.hash(token));
        try {
            repository.saveAndFlush(link);
        } catch (DataIntegrityViolationException e) {
            // Lost a race for the same code; for a generated code this is vanishingly rare.
            throw alias != null ? aliasTaken()
                    : new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "code_collision", "please retry");
        }
        return new CreatedLink(link, token);
    }

    /** Destination for an active link: 404 if unknown or deleted, 410 if expired. */
    @Transactional(readOnly = true)
    public String resolveForRedirect(String code) {
        return resolve(code).destination();
    }

    @Transactional(readOnly = true)
    public Redirect resolve(String code) {
        Link link = findLive(code);
        if (link.isExpiredAt(now())) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        return new Redirect(link.getId(), link.getOriginalUrl());
    }

    /**
     * Private stats (FR2): the same token rules as deletion. Expired links still have stats;
     * deleted ones do not. Daily counts cover the current UTC day and the previous 29, oldest
     * first, with zeroes for days without clicks.
     */
    @Transactional(readOnly = true)
    public LinkStats stats(String code, String managementToken) {
        Link link = findLive(code);
        authorize(link, managementToken);
        LocalDate today = LocalDate.ofInstant(now(), ZoneOffset.UTC);
        LocalDate from = today.minusDays(STATS_DAYS - 1);
        Map<LocalDate, Long> perDay = clicks.countPerDaySince(link.getId(), from).stream()
                .collect(Collectors.toMap(DailyCount::getDay, DailyCount::getClicks));
        List<DailyClicks> daily = new ArrayList<>(STATS_DAYS);
        for (LocalDate day = from; !day.isAfter(today); day = day.plusDays(1)) {
            daily.add(new DailyClicks(day, perDay.getOrDefault(day, 0L)));
        }
        return new LinkStats(clicks.countByLinkId(link.getId()), daily, clicks.findLastClickedAt(link.getId()));
    }

    /** Public metadata; expired links are still described, deleted ones are not. */
    @Transactional(readOnly = true)
    public Link metadata(String code) {
        return findLive(code);
    }

    /**
     * Tombstones the link and erases its clicks in one transaction (FR3), under the link's row
     * lock so a concurrent redirect cannot commit a click in between.
     */
    @Transactional
    public void delete(String code, String managementToken) {
        Link link = repository.lockByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
        authorize(link, managementToken);
        clicks.deleteByLinkId(link.getId());
        link.markDeleted(now());
        repository.save(link);
    }

    private void authorize(Link link, String managementToken) {
        if (managementToken == null || managementToken.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "missing_token", "X-Management-Token header is required");
        }
        if (!tokenService.matches(managementToken, link.getTokenHash())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "invalid_token", "management token does not match");
        }
    }

    private Link findLive(String code) {
        return repository.findByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
    }

    private String freshCode() {
        for (int i = 0; i < MAX_CODE_ATTEMPTS; i++) {
            String code = codeGenerator.next();
            // tombstones count as taken, so a deleted code is never handed out again
            if (!aliasPolicy.isReserved(code) && !repository.existsByCode(code)) {
                return code;
            }
        }
        throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "code_collision", "please retry");
    }

    private Instant now() {
        // the database stores microseconds; truncate so stored and returned timestamps agree
        return clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private static ApiException aliasTaken() {
        return new ApiException(HttpStatus.CONFLICT, "alias_taken", "alias is already in use");
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/ManagementTokenRateLimiter.java">
package com.example.shortener.service;

import java.time.Clock;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import com.example.shortener.config.ShortenerProperties;
import org.springframework.stereotype.Component;

/**
 * Throttles management-token guessing (FR10): at most N wrong tokens per client IP in a rolling
 * 60-second window, shared by the stats and delete endpoints. Only supplied-but-wrong tokens count;
 * a missing token is a client bug, not a guess, and a valid token is never blocked.
 * In memory and single-node by design; reset on restart.
 */
@Component
public class ManagementTokenRateLimiter {

    static final long WINDOW_MILLIS = 60_000;
    private static final int SWEEP_EVERY = 1024;

    private final Map<String, Deque<Long>> failures = new ConcurrentHashMap<>();
    private final AtomicLong records = new AtomicLong();
    private final int limit;
    private final Clock clock;

    public ManagementTokenRateLimiter(ShortenerProperties properties, Clock clock) {
        this.limit = properties.rateLimit().failedTokenAttemptsPerMinute();
        this.clock = clock;
    }

    /**
     * Records one wrong token from this client. Returns normally while the client is within the limit
     * (the caller then answers 403 invalid_token); throws 429 rate_limited once it is exceeded.
     */
    public void recordFailure(String clientAddress) {
        long now = clock.millis();
        Deque<Long> attempts = failures.computeIfAbsent(clientAddress, k -> new ArrayDeque<>());
        long retryAfterMillis = -1;
        synchronized (attempts) {
            prune(attempts, now);
            attempts.addLast(now);
            if (attempts.size() > limit) {
                retryAfterMillis = attempts.peekFirst() + WINDOW_MILLIS - now;
            }
        }
        if (records.incrementAndGet() % SWEEP_EVERY == 0) {
            sweep(now);
        }
        if (retryAfterMillis >= 0) {
            throw new RateLimitedException(Math.max(1, (retryAfterMillis + 999) / 1000),
                    "too many invalid management tokens; retry later");
        }
    }

    private static void prune(Deque<Long> attempts, long now) {
        while (!attempts.isEmpty() && attempts.peekFirst() <= now - WINDOW_MILLIS) {
            attempts.removeFirst();
        }
    }

    /** Drops clients with no attempts left in the window, so memory follows active clients only. */
    private void sweep(long now) {
        failures.entrySet().removeIf(entry -> {
            synchronized (entry.getValue()) {
                prune(entry.getValue(), now);
                return entry.getValue().isEmpty();
            }
        });
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/RateLimitedException.java">
package com.example.shortener.service;

import org.springframework.http.HttpStatus;

public class RateLimitedException extends ApiException {

    public RateLimitedException(long retryAfterSeconds) {
        this(retryAfterSeconds, "too many links created; retry later");
    }

    public RateLimitedException(long retryAfterSeconds, String message) {
        super(HttpStatus.TOO_MANY_REQUESTS, "rate_limited", message, retryAfterSeconds);
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/ServiceUnavailableException.java">
package com.example.shortener.service;

import org.springframework.http.HttpStatus;

/** The database could not serve a redirect (FR6): 503 with a fixed Retry-After, never retried here. */
public class ServiceUnavailableException extends ApiException {

    static final long RETRY_AFTER_SECONDS = 5;

    public ServiceUnavailableException() {
        super(HttpStatus.SERVICE_UNAVAILABLE, "service_unavailable", "the service is temporarily unavailable; retry later",
                RETRY_AFTER_SECONDS);
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/service/TokenService.java">
package com.example.shortener.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

import org.springframework.stereotype.Component;

/**
 * Management tokens: 256 random bits, unpadded base64url. Only the SHA-256 hash is stored;
 * the plaintext exists solely in the creation response.
 */
@Component
public class TokenService {

    private final SecureRandom random;

    public TokenService(SecureRandom random) {
        this.random = random;
    }

    public String newToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public String hash(String token) {
        return HexFormat.of().formatHex(sha256(token));
    }

    /** Constant-time comparison, so response timing reveals nothing about the stored hash. */
    public boolean matches(String token, String storedHash) {
        if (token == null || storedHash == null) {
            return false;
        }
        byte[] expected;
        try {
            expected = HexFormat.of().parseHex(storedHash);
        } catch (IllegalArgumentException e) {
            return false;
        }
        return MessageDigest.isEqual(sha256(token), expected);
    }

    private static byte[] sha256(String value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
</file>

<file path="url-shortener/src/main/resources/META-INF/spring/org.springframework.boot.actuate.autoconfigure.web.ManagementContextConfiguration.imports">
com.example.shortener.config.ManagementSecurityHeadersConfig
</file>

<file path="url-shortener/src/main/resources/application.yml">
spring:
  application:
    name: url-shortener
  datasource:
    # File-based H2 so links and tombstones survive restarts (NFR4). No external infrastructure.
    url: jdbc:h2:file:${shortener.data-dir}/shortener;DB_CLOSE_ON_EXIT=FALSE
    username: sa
  jpa:
    open-in-view: false
    hibernate:
      ddl-auto: validate   # Flyway owns the schema; Hibernate only checks it matches the entities
  flyway:
    enabled: true

server:
  port: 8080

management:
  # Operators only: a separate listener bound to loopback, unreachable from the public interface (FR15).
  server:
    port: 8081
    address: 127.0.0.1
  endpoints:
    web:
      exposure:
        include: health,metrics

shortener:
  data-dir: ./data
  rate-limit:
    creates-per-minute: 20
    failed-token-attempts-per-minute: 10
  max-api-body-bytes: 16384
  code-length: 8
</file>

<file path="url-shortener/src/main/resources/db/migration/V1__create_links.sql">
-- Links and tombstones. A deleted link keeps its row (code reserved forever) with the
-- destination URL and token hash erased, so codes and aliases are never reused (FR5).
CREATE TABLE links (
    id            BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    code          VARCHAR(32)              NOT NULL,
    original_url  VARCHAR(2048),
    custom_alias  BOOLEAN                  NOT NULL,
    created_at    TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    expires_at    TIMESTAMP(6) WITH TIME ZONE,
    token_hash    VARCHAR(64),
    deleted_at    TIMESTAMP(6) WITH TIME ZONE,
    CONSTRAINT uk_links_code UNIQUE (code),
    CONSTRAINT ck_links_tombstone CHECK (
        (deleted_at IS NULL AND original_url IS NOT NULL AND token_hash IS NOT NULL)
        OR (deleted_at IS NOT NULL AND original_url IS NULL AND token_hash IS NULL)
    )
);
</file>

<file path="url-shortener/src/main/resources/db/migration/V2__create_click_events.sql">
-- Click analytics: one row per successful redirect, with no visitor identifiers (NFR2).
-- V1 is applied and immutable; this forward migration only adds.
CREATE TABLE click_events (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    link_id     BIGINT                      NOT NULL,
    clicked_at  TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    click_date  DATE                        NOT NULL,   -- UTC day, for time-zone-stable daily counts
    CONSTRAINT fk_click_events_link FOREIGN KEY (link_id) REFERENCES links (id)
);

-- Daily counts over the 30-day window, and the lifetime count/latest click per link.
CREATE INDEX ix_click_events_link_date ON click_events (link_id, click_date);
CREATE INDEX ix_click_events_link_time ON click_events (link_id, clicked_at);
</file>

<file path="url-shortener/src/test/java/com/example/shortener/ClickPersistenceAndUpgradeTest.java">
package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;

import com.example.shortener.api.HealthController;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.TestSupportConfig;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** NFR3 and NFR4: click data survives restarts, and an existing V1 database upgrades in place. */
class ClickPersistenceAndUpgradeTest {

    @TempDir
    Path dataDir;

    @Test
    void TC_NFR3_01_clicksSurviveARestart() {
        String code;
        String token;
        try (ConfigurableApplicationContext first = start()) {
            var created = first.getBean(LinkService.class).create("https://example.com/persist", null, null);
            code = created.link().getCode();
            token = created.managementToken();
            Long id = created.link().getId();
            first.getBean(ClickRecorder.class).record(id);
            first.getBean(ClickRecorder.class).record(id);
        }
        try (ConfigurableApplicationContext second = start()) {
            assertThat(second.getBean(LinkService.class).stats(code, token).totalClicks()).isEqualTo(2);
        }
    }

    /** An existing deployment: a database migrated to V1 only, holding a link and a tombstone. */
    @Test
    void TC_NFR4_01_existingV1DatabaseUpgradesWithoutTouchingItsData() {
        String url = "jdbc:h2:file:" + dataDir.toAbsolutePath() + "/shortener;DB_CLOSE_ON_EXIT=FALSE";
        Flyway.configure().dataSource(url, "sa", "").locations("classpath:db/migration").target("1").load().migrate();
        JdbcTemplate v1 = new JdbcTemplate(new DriverManagerDataSource(url, "sa", ""));
        v1.update("INSERT INTO links (code, original_url, custom_alias, created_at, token_hash) VALUES "
                + "('old-link', 'https://example.com/old', TRUE, CURRENT_TIMESTAMP, ?)", "a".repeat(64));
        v1.update("INSERT INTO links (code, original_url, custom_alias, created_at, token_hash, deleted_at) VALUES "
                + "('old-tomb', NULL, TRUE, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)");

        try (ConfigurableApplicationContext app = start()) {
            Flyway flyway = app.getBean(Flyway.class);
            assertThat(flyway.info().applied()).extracting(m -> m.getVersion().getVersion()).containsExactly("1", "2");
            assertThat(flyway.validateWithResult().validationSuccessful).as("V1 checksum unchanged").isTrue();

            LinkService links = app.getBean(LinkService.class);
            assertThat(links.resolveForRedirect("old-link")).isEqualTo("https://example.com/old");
            Long oldId = links.metadata("old-link").getId();
            app.getBean(ClickRecorder.class).record(oldId);
            assertThat(app.getBean(JdbcTemplate.class).queryForObject(
                    "SELECT COUNT(*) FROM click_events WHERE link_id = ?", Long.class, oldId)).isEqualTo(1);
            assertThat(app.getBean(HealthController.class).health().getStatusCode()).isEqualTo(HttpStatus.OK);
        }
    }

    private ConfigurableApplicationContext start() {
        // Command-line args, not builder.properties(): those are defaults that application.yml overrides.
        return new SpringApplicationBuilder(ShortenerApplication.class, TestSupportConfig.class)
                .run("--shortener.data-dir=" + dataDir.toAbsolutePath(), "--server.port=0");
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/PersistenceRestartTest.java">
package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.file.Files;
import java.nio.file.Path;

import com.example.shortener.api.HealthController;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.TestSupportConfig;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.HttpStatus;

/**
 * NFR4: the real application, started twice on the same file-based H2 store under a temporary
 * data directory, as a restart would. Uses the production configuration apart from the data
 * directory, a random port, and stubbed DNS/clock.
 */
class PersistenceRestartTest {

    @TempDir
    Path dataDir;

    @Test
    void TC_NFR4_01_linksAndTombstonesSurviveRestartAndMigrationsAreApplied() {
        String activeCode;
        String tombstoneAlias = "kept-forever";
        try (ConfigurableApplicationContext first = start()) {
            LinkService links = first.getBean(LinkService.class);
            activeCode = links.create("https://example.com/persisted", null, null).link().getCode();
            var doomed = links.create("https://example.com/doomed", tombstoneAlias, null);
            links.delete(tombstoneAlias, doomed.managementToken());

            CreateRateLimiter limiter = first.getBean(CreateRateLimiter.class);
            for (int i = 0; i < 20; i++) {
                limiter.acquire("192.0.2.10");
            }
            assertThatThrownBy(() -> limiter.acquire("192.0.2.10")).isInstanceOf(RateLimitedException.class);
        }

        assertThat(Files.exists(dataDir.resolve("shortener.mv.db"))).as("file-based H2 under the data dir").isTrue();

        try (ConfigurableApplicationContext second = start()) {
            LinkService links = second.getBean(LinkService.class);
            assertThat(links.resolveForRedirect(activeCode)).isEqualTo("https://example.com/persisted");
            assertThatThrownBy(() -> links.resolveForRedirect(tombstoneAlias))
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.NOT_FOUND));
            assertThatThrownBy(() -> links.create("https://example.com/reuse", tombstoneAlias, null))
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.CONFLICT));

            assertThat(second.getBean(Flyway.class).info().applied()).extracting(m -> m.getVersion().getVersion())
                    .containsExactly("1", "2");
            second.getBean(CreateRateLimiter.class).acquire("192.0.2.10"); // in-memory limit reset by the restart
        }
    }

    /** TC-NFR4-02: starts from a clean directory with no external infrastructure and reports healthy. */
    @Test
    void TC_NFR4_02_startsLocallyAndReportsHealthy() {
        try (ConfigurableApplicationContext app = start()) {
            assertThat(app.getBean(HealthController.class).health().getStatusCode()).isEqualTo(HttpStatus.OK);
            assertThat(app.getBean(Flyway.class).info().current().getVersion().getVersion()).isEqualTo("2");
        }
    }

    private ConfigurableApplicationContext start() {
        // Command-line args, not builder.properties(): those are defaults that application.yml overrides.
        return new SpringApplicationBuilder(ShortenerApplication.class, TestSupportConfig.class)
                .run("--shortener.data-dir=" + dataDir.toAbsolutePath(), "--server.port=0");
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/ClickDeletionRaceTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * TC-FR3-03: a click being recorded and the link being deleted at the same moment. Each test
 * forces one interleaving by holding the first operation's transaction open (and so its row lock)
 * while the second starts; either way no click may survive the deletion.
 */
class ClickDeletionRaceTest extends IntegrationTest {

    @Autowired
    private ClickRecorder recorder;

    @Autowired
    private LinkService links;

    @Autowired
    private ClickEventRepository clicks;

    @Autowired
    private TransactionTemplate tx;

    @Test
    void TC_FR3_03_clickInFlightWhenDeleteArrivesIsErasedByTheDelete() throws Exception {
        JsonNode link = create("https://example.com/race-1");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch recordingHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> recording = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            recorder.record(id);            // joins this transaction: takes the row lock, inserts
            recordingHoldsLock.countDown();
            sleep(300);                     // keep the lock while the delete starts
        }));
        assertThat(recordingHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> deleting = CompletableFuture.runAsync(
                () -> links.delete(code, link.get("managementToken").asText()));

        CompletableFuture.allOf(recording, deleting).get(10, TimeUnit.SECONDS);
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
        assertThat(clicks.countByLinkId(id)).as("the delete waited for the click, then erased it").isZero();
    }

    @Test
    void TC_FR3_03_clickArrivingDuringDeleteIsNotRecordedAfterIt() throws Exception {
        JsonNode link = create("https://example.com/race-2");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch deleteHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> deleting = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            links.delete(code, link.get("managementToken").asText());  // takes the row lock, erases, tombstones
            deleteHoldsLock.countDown();
            sleep(300);                                                // commit only after the click starts
        }));
        assertThat(deleteHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> recording = CompletableFuture.runAsync(() -> recorder.record(id));

        CompletableFuture.allOf(recording, deleting).get(10, TimeUnit.SECONDS);
        assertThat(clicks.countByLinkId(id)).as("the click waited, then saw the tombstone and recorded nothing").isZero();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/ClickFailureIsolationTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

/** NFR1: analytics are best-effort; a failure to record a click never changes the redirect. */
class ClickFailureIsolationTest {

    /** TC-FR1-03: the controller alone, with a recorder that throws. */
    @Test
    void TC_FR1_03_recorderFailureStillReturnsTheRedirect() {
        LinkService links = mock(LinkService.class);
        ClickRecorder recorder = mock(ClickRecorder.class);
        when(links.resolve("abc12345")).thenReturn(new LinkService.Redirect(7L, "https://example.com/x"));
        doThrow(new DataAccessResourceFailureException("click store down")).when(recorder).record(any());

        var response = new RedirectController(links, recorder).redirect("abc12345");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FOUND);
        assertThat(response.getHeaders().getLocation()).hasToString("https://example.com/x");
        assertThat(response.getHeaders().getCacheControl()).contains("no-store");
    }

    /** TC-NFR1-01: the same failure through the running application. */
    @Nested
    class ThroughTheRunningApplication extends IntegrationTest {

        @MockitoBean
        private ClickRecorder recorder;

        @Test
        void TC_NFR1_01_redirectIsUnchangedWhenClickPersistenceFails() throws Exception {
            doThrow(new DataAccessResourceFailureException("click store down")).when(recorder).record(any());
            String code = create("https://example.com/nfr1-01").get("code").asText();
            mvc.perform(get("/" + code))
                    .andExpect(status().isFound())
                    .andExpect(header().string("Location", "https://example.com/nfr1-01"))
                    .andExpect(header().string("Cache-Control", containsString("no-store")));
        }
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/HealthTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;

class HealthTest {

    @Nested
    class WithRunningServiceAndStore extends IntegrationTest {

        @Test
        void TC_FR6_01_healthyServiceReturns200Up() throws Exception {
            mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("UP"));
        }
    }

    /**
     * TC-FR6-02: the persistence check failing while the app keeps running. The controller is
     * exercised directly with a store that refuses connections; stopping the shared test
     * database would break every other test in the context.
     */
    @Test
    void TC_FR6_02_unavailableStoreReturns503Down() {
        JdbcTemplate failing = mock(JdbcTemplate.class);
        when(failing.queryForObject(anyString(), eq(Integer.class)))
                .thenThrow(new DataAccessResourceFailureException("connection refused"));

        var response = new HealthController(failing).health();

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(response.getBody()).containsEntry("status", "DOWN");
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/LinkCreationTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class LinkCreationTest extends IntegrationTest {

    @Test
    void TC_FR1_01_generatedCodeCreationResponse() throws Exception {
        postLink(Map.of("url", "http://example.com/tc-fr1-01"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.code").value(matchesPattern("[A-Za-z0-9_-]{8}")))
                .andExpect(jsonPath("$.shortPath").value(matchesPattern("/[A-Za-z0-9_-]{8}")))
                .andExpect(jsonPath("$.managementToken").isNotEmpty());

        JsonNode created = create("https://example.com/tc-fr1-01b");
        assertThat(created.get("shortPath").asText()).isEqualTo("/" + created.get("code").asText());
    }

    @Test
    void TC_FR1_02_customAliasIsUsedExactlyAndCaseSensitively() throws Exception {
        String alias = uniqueAlias("MiXeD");
        JsonNode created = create("https://example.com/tc-fr1-02", alias, null);
        assertThat(created.get("code").asText()).isEqualTo(alias);
        assertThat(created.get("shortPath").asText()).isEqualTo("/" + alias);

        // a different-case spelling is a distinct alias, not a conflict
        create("https://example.com/tc-fr1-02b", alias.toLowerCase(), null);
    }

    @ParameterizedTest
    @ValueSource(strings = {"ab", "a234567890123456789012345678901234", "has space", "dot.ted", "slash/x", "ünï",
            "api", "health", "links", "API", "Health"})
    void TC_FR1_03_invalidOrReservedAliasIsRejected(String alias) throws Exception {
        long before = repository.count();
        postLink(Map.of("url", "https://example.com/tc-fr1-03", "alias", alias)).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_FR1_03_boundaryAliasLengthsAreAccepted() throws Exception {
        create("https://example.com/tc-fr1-03-min", "x" + uniqueAlias("").substring(1, 3), null);
        create("https://example.com/tc-fr1-03-max", ("max-" + uniqueAlias("") + "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").substring(0, 32), null);
    }

    @Test
    void TC_FR1_04_aliasOfActiveLinkOrTombstoneConflicts() throws Exception {
        String active = uniqueAlias("taken");
        create("https://example.com/tc-fr1-04", active, null);
        postLink(Map.of("url", "https://example.com/other", "alias", active)).andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("alias_taken"));

        String deleted = uniqueAlias("tomb");
        JsonNode created = create("https://example.com/tc-fr1-04b", deleted, null);
        mvc.perform(delete("/api/links/" + deleted)
                .header("X-Management-Token", created.get("managementToken").asText())).andExpect(status().isNoContent());
        postLink(Map.of("url", "https://example.com/other", "alias", deleted)).andExpect(status().isConflict());
    }

    @Test
    void TC_FR2_02_expiryAtOrBeforeCreationOrMalformedIsRejected() throws Exception {
        long before = repository.count();
        // the test clock is fixed at 2030-01-01T00:00:00Z
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "2030-01-01T00:00:00Z")).andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid_expiry"));
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "2029-12-31T23:59:59Z")).andExpect(status().isBadRequest());
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "not-a-timestamp")).andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid_request"));
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_FR2_02_offsetExpiryIsNormalizedToUtc() throws Exception {
        String alias = uniqueAlias("utc");
        create("https://example.com/utc", alias, "2030-01-01T05:30:00+05:00");
        mvc.perform(get("/api/links/" + alias))
                .andExpect(jsonPath("$.expiresAt").value("2030-01-01T00:30:00Z"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"not a url", "http://", "javascript:alert(1)", "ftp://example.com/file", "mailto:a@example.com",
            "//example.com/no-scheme", "file:///etc/passwd"})
    void TC_NFR2_01_malformedOrNonHttpUrlIsRejected(String url) throws Exception {
        long before = repository.count();
        postLink(Map.of("url", url)).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_NFR2_01_urlLengthLimitIs2048() throws Exception {
        String prefix = "https://example.com/";
        String exactly2048 = prefix + "a".repeat(2048 - prefix.length());
        create(exactly2048);
        long before = repository.count();
        postLink(Map.of("url", exactly2048 + "a")).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_NFR2_01_missingUrlOrBodyIsRejected() throws Exception {
        postLink(Map.of("alias", uniqueAlias("nourl"))).andExpect(status().isBadRequest());
        mvc.perform(post("/api/links")
                .contentType("application/json").content("{\"url\":")).andExpect(status().isBadRequest());
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/LinkLifecycleTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.Link;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;

class LinkLifecycleTest extends IntegrationTest {

    private static final String TOKEN = "X-Management-Token";

    // --- FR3 redirect -------------------------------------------------------------------------

    @Test
    void TC_FR3_01_activeLinkRedirectsWith302AndNoStore() throws Exception {
        String url = "https://example.com/tc-fr3-01?q=1&r=two";
        String code = create(url).get("code").asText();
        mvc.perform(get("/" + code))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", url))
                .andExpect(header().string("Cache-Control", containsString("no-store")));
    }

    @Test
    void TC_FR3_02_expiredLinkReturns410WithoutLocation() throws Exception {
        String code = create("https://example.com/tc-fr3-02", null, "2030-01-01T00:00:10Z").get("code").asText();
        clock.advance(Duration.ofSeconds(11));
        mvc.perform(get("/" + code))
                .andExpect(status().isGone())
                .andExpect(header().doesNotExist("Location"))
                .andExpect(jsonPath("$.error").value("expired"));
    }

    @Test
    void TC_FR3_03_unknownAndDeletedCodesReturn404WithoutLocation() throws Exception {
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()).andExpect(header().doesNotExist("Location"));
        JsonNode created = create("https://example.com/tc-fr3-03");
        String code = created.get("code").asText();
        deleteWith(code, created.get("managementToken").asText()).andExpect(status().isNoContent());
        mvc.perform(get("/" + code)).andExpect(status().isNotFound()).andExpect(header().doesNotExist("Location"));
    }

    // --- FR2 expiry -----------------------------------------------------------------------------

    @Test
    void TC_FR2_01_redirectsBeforeExpiryAnd410AtAndAfterIt() throws Exception {
        Instant expiry = MutableClock.START.plus(Duration.ofMinutes(5));
        String code = create("https://example.com/tc-fr2-01", null, expiry.toString()).get("code").asText();

        clock.set(expiry.minusNanos(1_000)); // one microsecond before
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        clock.set(expiry); // exactly at the instant: expired
        mvc.perform(get("/" + code)).andExpect(status().isGone());
        clock.set(expiry.plus(Duration.ofDays(1)));
        mvc.perform(get("/" + code)).andExpect(status().isGone());
    }

    @Test
    void TC_FR2_03_expiredLinkKeepsPublicMetadata() throws Exception {
        String alias = uniqueAlias("exp");
        create("https://example.com/tc-fr2-03", alias, "2030-01-01T00:01:00Z");
        clock.advance(Duration.ofHours(1));
        mvc.perform(get("/api/links/" + alias))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.originalUrl").value("https://example.com/tc-fr2-03"))
                .andExpect(jsonPath("$.expiresAt").value("2030-01-01T00:01:00Z"));
        assertThat(repository.findByCode(alias)).get().extracting(Link::isDeleted).isEqualTo(false);
    }

    // --- FR4 metadata ---------------------------------------------------------------------------

    @Test
    void TC_FR4_01_publicMetadataWithoutCredentials() throws Exception {
        String code = create("https://example.com/tc-fr4-01").get("code").asText();
        mvc.perform(get("/api/links/" + code))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(code))
                .andExpect(jsonPath("$.alias").value(nullValue()))
                .andExpect(jsonPath("$.originalUrl").value("https://example.com/tc-fr4-01"))
                .andExpect(jsonPath("$.createdAt").value("2030-01-01T00:00:00Z"))
                .andExpect(jsonPath("$.expiresAt").value(nullValue()))
                .andExpect(jsonPath("$.managementToken").doesNotExist());

        String alias = uniqueAlias("meta");
        create("https://example.com/tc-fr4-01b", alias, "2031-06-01T12:00:00Z");
        mvc.perform(get("/api/links/" + alias))
                .andExpect(jsonPath("$.alias").value(alias))
                .andExpect(jsonPath("$.expiresAt").value("2031-06-01T12:00:00Z"));
    }

    @Test
    void TC_FR4_02_metadataForUnknownAndDeletedCodesIs404() throws Exception {
        mvc.perform(get("/api/links/Zz9Zz9Zz")).andExpect(status().isNotFound());
        JsonNode created = create("https://example.com/tc-fr4-02");
        String code = created.get("code").asText();
        deleteWith(code, created.get("managementToken").asText()).andExpect(status().isNoContent());
        mvc.perform(get("/api/links/" + code)).andExpect(status().isNotFound());
    }

    // --- FR5 deletion ---------------------------------------------------------------------------

    @Test
    void TC_FR5_01_authorizedDeletionLeavesTombstoneThatReservesTheCode() throws Exception {
        String alias = uniqueAlias("del");
        JsonNode created = create("https://example.com/tc-fr5-01", alias, null);

        deleteWith(alias, created.get("managementToken").asText())
                .andExpect(status().isNoContent())
                .andExpect(result -> assertThat(result.getResponse().getContentAsString()).isEmpty());

        Link tombstone = repository.findByCode(alias).orElseThrow();
        assertThat(tombstone.isDeleted()).isTrue();
        assertThat(tombstone.getOriginalUrl()).isNull();
        assertThat(tombstone.getTokenHash()).isNull();
        mvc.perform(get("/" + alias)).andExpect(status().isNotFound());
        mvc.perform(get("/api/links/" + alias)).andExpect(status().isNotFound());
        postLink(java.util.Map.of("url", "https://example.com/reuse", "alias", alias)).andExpect(status().isConflict());
    }

    @Test
    void TC_FR5_02_missingTokenIs401AndLinkSurvives() throws Exception {
        String code = create("https://example.com/tc-fr5-02").get("code").asText();
        mvc.perform(delete("/api/links/" + code)).andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("missing_token"));
        mvc.perform(get("/" + code)).andExpect(status().isFound())
                .andExpect(header().string("Location", "https://example.com/tc-fr5-02"));
    }

    @Test
    void TC_FR5_03_invalidTokenIs403AndLinkSurvives() throws Exception {
        JsonNode created = create("https://example.com/tc-fr5-03");
        String code = created.get("code").asText();
        deleteWith(code, "wrong-" + created.get("managementToken").asText()).andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("invalid_token"));
        assertThat(repository.findByCode(code)).get().extracting(Link::isDeleted).isEqualTo(false);
        mvc.perform(get("/" + code)).andExpect(status().isFound());
    }

    @Test
    void TC_FR5_04_deletingUnknownOrAlreadyDeletedCodeIs404() throws Exception {
        deleteWith("Zz9Zz9Zz", "any-token").andExpect(status().isNotFound());
        JsonNode created = create("https://example.com/tc-fr5-04");
        String code = created.get("code").asText();
        String token = created.get("managementToken").asText();
        deleteWith(code, token).andExpect(status().isNoContent());
        deleteWith(code, token).andExpect(status().isNotFound());
    }

    @Test
    void TC_FR5_05_onlyTheTokenHashIsPersistedAndTheTokenIsNeverEchoed() throws Exception {
        JsonNode created = create("https://example.com/tc-fr5-05");
        String code = created.get("code").asText();
        String token = created.get("managementToken").asText();
        assertThat(token).matches("[A-Za-z0-9_-]{43}"); // 256 bits, unpadded base64url

        Link stored = repository.findByCode(code).orElseThrow();
        assertThat(stored.getTokenHash()).isEqualTo(sha256Hex(token)).doesNotContain(token);

        String metadata = mvc.perform(get("/api/links/" + code)).andReturn().getResponse().getContentAsString();
        String redirectHeaders = String.join(";", mvc.perform(get("/" + code)).andReturn().getResponse().getHeaderValues("Location")
                .stream().map(Object::toString).toList());
        assertThat(metadata).doesNotContain(token).doesNotContain(stored.getTokenHash());
        assertThat(redirectHeaders).doesNotContain(token);
    }

    private org.springframework.test.web.servlet.ResultActions deleteWith(String code, String token) throws Exception {
        return mvc.perform(delete("/api/links/" + code).header(TOKEN, token));
    }

    private static String sha256Hex(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/LinkStatsTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.ResultActions;

/** Click analytics through the running application: counting, the stats contract, privacy, deletion. */
class LinkStatsTest extends IntegrationTest {

    private static final String TOKEN = "X-Management-Token";

    @Autowired
    private ClickEventRepository clicks;

    @Autowired
    private JdbcTemplate jdbc;

    // --- FR1 counting -------------------------------------------------------------------------

    @Test
    void TC_FR1_01_eachSuccessfulRedirectIsOneClickAndTheRedirectIsUnchanged() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-01");
        String code = link.get("code").asText();
        for (int i = 0; i < 3; i++) {
            mvc.perform(get("/" + code))
                    .andExpect(status().isFound())
                    .andExpect(header().string("Location", "https://example.com/tc-fr1-01"))
                    .andExpect(header().string("Cache-Control", containsString("no-store")));
        }
        stats(code, link).andExpect(status().isOk()).andExpect(jsonPath("$.totalClicks").value(3));
    }

    @Test
    void TC_FR1_02_unknownAndExpiredRedirectsRecordNoClick() throws Exception {
        long before = clicks.count();
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound());
        JsonNode link = create("https://example.com/tc-fr1-02", null, "2030-01-01T00:00:05Z");
        clock.advance(Duration.ofSeconds(10));
        mvc.perform(get("/" + link.get("code").asText())).andExpect(status().isGone());
        assertThat(clicks.count()).isEqualTo(before);
    }

    // --- FR2 stats contract ----------------------------------------------------------------------

    @Test
    void TC_FR2_01_lifetimeTotalThirtyUtcDaysOldestFirstAndLatestClick() throws Exception {
        JsonNode link = create("https://example.com/tc-fr2-01");
        String code = link.get("code").asText();
        clickAt(code, "2030-01-01T10:00:00Z");                  // outside the window: lifetime total only
        clickAt(code, "2030-01-17T00:00:00Z");                  // first day of the window, at midnight UTC
        clickAt(code, "2030-02-10T23:59:59Z");
        clickAt(code, "2030-02-10T08:00:00Z");
        Instant latest = Instant.parse("2030-02-15T11:59:00Z");
        clickAt(code, latest.toString());
        clock.set(Instant.parse("2030-02-15T12:00:00Z"));       // window: 2030-01-17 .. 2030-02-15

        JsonNode s = json.readTree(stats(code, link).andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertThat(s.get("totalClicks").asLong()).isEqualTo(5);
        JsonNode days = s.get("dailyClicks");
        assertThat(days).hasSize(30);
        assertThat(days.get(0).get("date").asText()).isEqualTo("2030-01-17");
        assertThat(days.get(0).get("clicks").asLong()).isEqualTo(1);
        assertThat(days.get(29).get("date").asText()).isEqualTo("2030-02-15");
        assertThat(days.get(29).get("clicks").asLong()).isEqualTo(1);
        assertThat(dayCount(days, "2030-02-10")).isEqualTo(2);
        assertThat(dayCount(days, "2030-02-11")).isZero();
        for (int i = 1; i < days.size(); i++) {
            assertThat(days.get(i).get("date").asText()).isGreaterThan(days.get(i - 1).get("date").asText());
        }
        assertThat(s.get("lastClickedAt").asText()).isEqualTo(latest.toString());
    }

    @Test
    void TC_FR2_02_linkWithoutClicksHasZeroesAndNullLastClick() throws Exception {
        JsonNode link = create("https://example.com/tc-fr2-02");
        JsonNode s = json.readTree(stats(link.get("code").asText(), link).andReturn().getResponse().getContentAsString());
        assertThat(s.get("totalClicks").asLong()).isZero();
        assertThat(s.get("dailyClicks")).hasSize(30).allSatisfy(d -> assertThat(d.get("clicks").asLong()).isZero());
        assertThat(s.get("dailyClicks").get(29).get("date").asText()).isEqualTo("2030-01-01");
        assertThat(s.get("lastClickedAt").isNull()).isTrue();
    }

    @Test
    void TC_FR2_03_missingOrBlankTokenIs401() throws Exception {
        String code = create("https://example.com/tc-fr2-03").get("code").asText();
        mvc.perform(get("/api/links/" + code + "/stats")).andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("missing_token"));
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, "  ")).andExpect(status().isUnauthorized());
    }

    @Test
    void TC_FR2_04_wrongTokenIs403AndRevealsNoStats() throws Exception {
        String code = create("https://example.com/tc-fr2-04").get("code").asText();
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, "not-the-token"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("invalid_token"))
                .andExpect(jsonPath("$.totalClicks").doesNotExist());
    }

    @Test
    void TC_FR2_05_unknownCodeIs404() throws Exception {
        mvc.perform(get("/api/links/Zz9Zz9Zz/stats").header(TOKEN, "anything"))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.totalClicks").doesNotExist());
    }

    // --- FR3 expiry and deletion -----------------------------------------------------------------

    @Test
    void TC_FR3_01_expiredLinkStillHasStats() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-01", null, "2030-01-01T01:00:00Z");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        clock.advance(Duration.ofHours(2));
        stats(code, link).andExpect(status().isOk()).andExpect(jsonPath("$.totalClicks").value(1));
    }

    @Test
    void TC_FR3_02_deletionErasesEveryClickAndKeepsTheTombstone() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-02");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code));
        mvc.perform(get("/" + code));
        Long linkId = repository.findByCode(code).orElseThrow().getId();
        assertThat(clicks.countByLinkId(linkId)).isEqualTo(2);

        mvc.perform(delete("/api/links/" + code).header(TOKEN, link.get("managementToken").asText()))
                .andExpect(status().isNoContent());
        assertThat(clicks.countByLinkId(linkId)).isZero();
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
    }

    @Test
    void TC_FR3_04_deletedLinkHasNoStats() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-04");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();
        mvc.perform(delete("/api/links/" + code).header(TOKEN, token)).andExpect(status().isNoContent());
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, token)).andExpect(status().isNotFound());
    }

    // --- FR5 / NFR2 privacy ----------------------------------------------------------------------

    @Test
    void TC_FR5_01_statsReportClickCountsOnly() throws Exception {
        JsonNode link = create("https://example.com/tc-fr5-01");
        mvc.perform(get("/" + link.get("code").asText()));
        JsonNode s = json.readTree(stats(link.get("code").asText(), link).andReturn().getResponse().getContentAsString());
        assertThat(fieldNames(s)).containsExactlyInAnyOrder("totalClicks", "dailyClicks", "lastClickedAt");
        assertThat(fieldNames(s.get("dailyClicks").get(0))).containsExactlyInAnyOrder("date", "clicks");
    }

    @Test
    void TC_NFR2_01_noVisitorDataIsStoredEvenWhenTheRequestCarriesIt() throws Exception {
        JsonNode link = create("https://example.com/tc-nfr2-01");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code).with(request -> {
            request.setRemoteAddr("203.0.113.77");
            return request;
        }).header("User-Agent", "Mozilla/5.0 PrivacyProbe").header("X-Forwarded-For", "198.51.100.23")
                .header("Cookie", "visitor=probe-cookie-123").header("Referer", "https://referrer.example/probe"))
                .andExpect(status().isFound());

        List<String> columns = jdbc.queryForList(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'CLICK_EVENTS'", String.class);
        assertThat(columns).containsExactlyInAnyOrder("ID", "LINK_ID", "CLICKED_AT", "CLICK_DATE");

        Long linkId = repository.findByCode(code).orElseThrow().getId();
        String stored = jdbc.queryForList("SELECT * FROM click_events WHERE link_id = ?", linkId).toString();
        for (String probe : List.of("203.0.113.77", "198.51.100.23", "PrivacyProbe", "probe-cookie-123", "referrer.example")) {
            assertThat(stored).doesNotContain(probe);
        }
    }

    private ResultActions stats(String code, JsonNode created) throws Exception {
        return mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, created.get("managementToken").asText()));
    }

    private void clickAt(String code, String instant) throws Exception {
        clock.set(Instant.parse(instant));
        mvc.perform(get("/" + code)).andExpect(status().isFound());
    }

    private static long dayCount(JsonNode days, String date) {
        for (JsonNode d : days) {
            if (d.get("date").asText().equals(date)) {
                return d.get("clicks").asLong();
            }
        }
        throw new AssertionError("no entry for " + date);
    }

    private static Set<String> fieldNames(JsonNode node) {
        Set<String> names = new HashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/NoOutboundFetchTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.net.InetAddress;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import com.example.shortener.service.DestinationPolicy;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;

/**
 * TC-NFR2-06: the service validates destinations but never fetches them. Two observable checks:
 * (1) no HTTP client is wired into the application, and (2) the only network-facing action
 * during create + redirect is the single DNS lookup at creation, made through the resolver.
 */
class NoOutboundFetchTest extends IntegrationTest {

    @Autowired
    private ApplicationContext context;

    @Test
    void TC_NFR2_06_noHttpClientBeansExist() {
        for (String type : List.of("org.springframework.web.client.RestTemplate", "org.springframework.web.client.RestClient",
                "org.springframework.web.reactive.function.client.WebClient", "java.net.http.HttpClient")) {
            try {
                assertThat(context.getBeanNamesForType(Class.forName(type))).as(type).isEmpty();
            } catch (ClassNotFoundException absent) {
                // not even on the classpath
            }
        }
    }

    @Test
    void TC_NFR2_06_createAndRedirectOnlyResolveOnceAndNeverFetch() throws Exception {
        List<String> lookups = new CopyOnWriteArrayList<>();
        DestinationPolicy recording = new DestinationPolicy(host -> {
            lookups.add(host);
            return new InetAddress[] {InetAddress.getByName("93.184.216.34")};
        });
        recording.validate("https://probe.example/path");
        assertThat(lookups).containsExactly("probe.example");

        String code = create("https://probe.example/path").get("code").asText();
        int before = lookups.size();
        mvc.perform(get("/" + code)).andExpect(status().isFound())
                .andExpect(header().string("Location", "https://probe.example/path"));
        assertThat(lookups).hasSize(before); // redirecting does not touch the destination at all
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/RateLimitTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.concurrent.atomic.AtomicInteger;

import com.example.shortener.config.ShortenerProperties;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.TestSupportConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/** NFR3 with the production limit of 20 creates per minute per peer IP. */
@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:ratelimit-${random.uuid};DB_CLOSE_DELAY=-1")
@AutoConfigureMockMvc
@Import(TestSupportConfig.class)
class RateLimitTest {

    private static final AtomicInteger NEXT_IP = new AtomicInteger(1);

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ShortenerProperties properties;

    @Test
    void TC_NFR3_01_twentyCreatesPerMinuteThen429WithRetryAfter() throws Exception {
        assertThat(properties.rateLimit().createsPerMinute()).isEqualTo(20);
        String ip = freshIp();
        for (int i = 0; i < 20; i++) {
            createFrom(ip, null).andExpect(status().isCreated());
        }
        createFrom(ip, null)
                .andExpect(status().isTooManyRequests())
                .andExpect(header().exists("Retry-After"))
                .andExpect(result -> assertThat(Long.parseLong(result.getResponse().getHeader("Retry-After")))
                        .isBetween(1L, 60L));
    }

    @Test
    void TC_NFR3_02_bucketsArePerPeerIpAndIgnoreXForwardedFor() throws Exception {
        String exhausted = freshIp();
        for (int i = 0; i < 20; i++) {
            createFrom(exhausted, null).andExpect(status().isCreated());
        }
        createFrom(exhausted, "203.0.113.99").andExpect(status().isTooManyRequests()); // spoofed header: same bucket
        createFrom(freshIp(), null).andExpect(status().isCreated());                   // another peer: unaffected
    }

    @Test
    void TC_NFR3_03_rejectedAttemptsConsumeTokens() throws Exception {
        String ip = freshIp();
        mvc.perform(post("/api/links").with(peer(ip)).contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"ftp://example.com/invalid\"}")).andExpect(status().isBadRequest());
        for (int i = 0; i < 19; i++) {
            createFrom(ip, null).andExpect(status().isCreated());
        }
        createFrom(ip, null).andExpect(status().isTooManyRequests());
    }

    /**
     * TC-NFR3-03 (restart): limiter state is in memory only, so a new instance, which is what a
     * restart creates, starts with a full bucket. The full application restart is covered in
     * PersistenceRestartTest.
     */
    @Test
    void TC_NFR3_03_freshLimiterAfterRestartAllowsTheIpAgain() {
        CreateRateLimiter beforeRestart = new CreateRateLimiter(properties);
        for (int i = 0; i < 20; i++) {
            beforeRestart.acquire("198.51.100.7");
        }
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> beforeRestart.acquire("198.51.100.7"))
                .isInstanceOf(RateLimitedException.class);

        new CreateRateLimiter(properties).acquire("198.51.100.7"); // does not throw
    }

    private ResultActions createFrom(String ip, String forwardedFor) throws Exception {
        var request = post("/api/links").with(peer(ip)).contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"https://example.com/rl\"}");
        if (forwardedFor != null) {
            request.header("X-Forwarded-For", forwardedFor);
        }
        return mvc.perform(request);
    }

    private static org.springframework.test.web.servlet.request.RequestPostProcessor peer(String ip) {
        return request -> {
            request.setRemoteAddr(ip);
            return request;
        };
    }

    private static String freshIp() {
        int n = NEXT_IP.getAndIncrement();
        return "198.18." + (n / 250) + "." + (n % 250 + 1);
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/api/RedirectLatencyTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import java.util.Arrays;

import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;

/**
 * TC-NFR1-01: indicative, in-process latency check (not a production SLO). 1,000 sequential
 * warm-up redirects, then 1,000 measured ones from a single client on the local machine.
 */
class RedirectLatencyTest extends IntegrationTest {

    @Test
    void TC_NFR1_01_redirectP99IsBelow50ms() throws Exception {
        String code = create("https://example.com/tc-nfr1-01").get("code").asText();
        for (int i = 0; i < 1_000; i++) {
            assertThat(mvc.perform(get("/" + code)).andReturn().getResponse().getStatus()).isEqualTo(302);
        }

        long[] nanos = new long[1_000];
        for (int i = 0; i < nanos.length; i++) {
            long start = System.nanoTime();
            int status = mvc.perform(get("/" + code)).andReturn().getResponse().getStatus();
            nanos[i] = System.nanoTime() - start;
            assertThat(status).isEqualTo(302);
        }
        Arrays.sort(nanos);
        double p99Millis = nanos[(int) Math.ceil(0.99 * nanos.length) - 1] / 1_000_000.0;
        System.out.printf("TC-NFR1-01 redirect latency: p50=%.3f ms, p99=%.3f ms%n",
                nanos[nanos.length / 2] / 1_000_000.0, p99Millis);
        assertThat(p99Millis).isLessThan(50.0);
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/service/DestinationPolicyTest.java">
package com.example.shortener.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;

import com.example.shortener.support.StubHostResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class DestinationPolicyTest {

    private StubHostResolver resolver;
    private DestinationPolicy policy;

    @BeforeEach
    void setUp() {
        resolver = new StubHostResolver();
        policy = new DestinationPolicy(resolver);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "http://localhost/", "http://LOCALHOST:8080/x", "http://api.localhost/",
            "http://127.0.0.1/", "http://127.255.0.9/", "http://0.0.0.0/",
            "http://10.0.0.1/", "http://172.16.5.4/", "http://172.31.255.255/", "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data", "http://224.0.0.1/", "http://239.255.255.250/",
            "http://[::1]/", "http://[::]/", "http://[fe80::1]/", "http://[fc00::1]/", "http://[fd12:3456::7]/",
            "http://[ff02::1]/", "http://[::ffff:127.0.0.1]/"
    })
    void TC_NFR2_02_localhostAndProhibitedLiteralsAreRejected(String url) {
        assertThatThrownBy(() -> policy.validate(url)).isInstanceOfSatisfying(ApiException.class,
                e -> assertThat(e.getError()).isEqualTo("prohibited_destination"));
    }

    @Test
    void TC_NFR2_03_hostnameResolvingOnlyToProhibitedAddressesIsRejected() {
        resolver.answers.put("intranet.example", List.of("10.1.2.3", "fd00::5"));
        assertThatThrownBy(() -> policy.validate("https://intranet.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_03_mixedPublicAndProhibitedResultsAreRejected() {
        resolver.answers.put("rebind.example", List.of(StubHostResolver.PUBLIC_IP, "127.0.0.1"));
        resolver.answers.put("rebind6.example", List.of("2606:2800:220:1:248:1893:25c8:1946", "fe80::1"));
        assertThatThrownBy(() -> policy.validate("https://rebind.example/")).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> policy.validate("https://rebind6.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_04_resolutionFailureOrNoAddressesFailsClosed() {
        resolver.failing.put("timeout.example", true);
        assertThatThrownBy(() -> policy.validate("https://timeout.example/"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getError()).isEqualTo("invalid_url"));

        DestinationPolicy empty = new DestinationPolicy(host -> new InetAddress[0]);
        assertThatThrownBy(() -> empty.validate("https://empty.example/")).isInstanceOf(ApiException.class);

        DestinationPolicy nulls = new DestinationPolicy(host -> null);
        assertThatThrownBy(() -> nulls.validate("https://null.example/")).isInstanceOf(ApiException.class);

        DestinationPolicy throwing = new DestinationPolicy(host -> {
            throw new UnknownHostException("SERVFAIL");
        });
        assertThatThrownBy(() -> throwing.validate("https://servfail.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_05_publicDestinationsAreAccepted() {
        resolver.answers.put("dual.example", List.of(StubHostResolver.PUBLIC_IP, "2606:2800:220:1:248:1893:25c8:1946"));
        String prefix = "https://dual.example/";
        String longest = prefix + "p".repeat(2048 - prefix.length());

        for (String url : List.of("http://example.com", "https://example.com/path?q=1#frag", "HTTPS://Example.COM/x",
                "https://dual.example/", "http://93.184.216.34/", "http://[2606:2800:220:1:248:1893:25c8:1946]/", longest)) {
            assertThatCode(() -> policy.validate(url)).as(url).doesNotThrowAnyException();
        }
    }

    @Test
    void TC_NFR2_05_lengthLimitIsExclusiveAbove2048() {
        String prefix = "https://example.com/";
        assertThatThrownBy(() -> policy.validate(prefix + "p".repeat(2049 - prefix.length())))
                .isInstanceOf(ApiException.class);
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/service/LinkServiceTest.java">
package com.example.shortener.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.security.SecureRandom;

import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import com.example.shortener.support.MutableClock;
import com.example.shortener.support.StubHostResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class LinkServiceTest {

    private LinkRepository repository;
    private CodeGenerator codes;
    private LinkService service;

    @BeforeEach
    void setUp() {
        repository = mock(LinkRepository.class);
        codes = mock(CodeGenerator.class);
        when(repository.saveAndFlush(any(Link.class))).thenAnswer(invocation -> invocation.getArgument(0));
        service = new LinkService(repository, new DestinationPolicy(new StubHostResolver()), new AliasPolicy(), codes,
                new TokenService(new SecureRandom()), mock(ClickEventRepository.class), new MutableClock());
    }

    /** TC-FR1-05: active and tombstoned codes both count as taken; the first unused code wins. */
    @Test
    void TC_FR1_05_collidingGeneratedCodesAreRetried() {
        when(codes.next()).thenReturn("ActiveC1", "Tombstn2", "FreeCod3");
        when(repository.existsByCode("ActiveC1")).thenReturn(true);  // an active link
        when(repository.existsByCode("Tombstn2")).thenReturn(true);  // a deleted link's tombstone
        when(repository.existsByCode("FreeCod3")).thenReturn(false);

        LinkService.CreatedLink created = service.create("https://example.com/x", null, null);

        assertThat(created.link().getCode()).isEqualTo("FreeCod3");
        assertThat(created.link().isCustomAlias()).isFalse();
    }

    @Test
    void TC_FR1_05_generationGivesUpAfterBoundedAttempts() {
        when(codes.next()).thenReturn("Taken000");
        when(repository.existsByCode("Taken000")).thenReturn(true);

        assertThatThrownBy(() -> service.create("https://example.com/x", null, null))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE));
        verify(repository, never()).saveAndFlush(any());
    }

    @Test
    void TC_FR1_05_reservedWordsAreNeverHandedOutAsGeneratedCodes() {
        when(codes.next()).thenReturn("HEALTH", "FreeCod4");
        when(repository.existsByCode(any())).thenReturn(false);
        assertThat(service.create("https://example.com/x", null, null).link().getCode()).isEqualTo("FreeCod4");
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/support/IntegrationTest.java">
package com.example.shortener.support;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.domain.LinkRepository;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * Full Spring context over an isolated in-memory H2 database (migrated by Flyway), with a
 * controllable clock and stubbed DNS. The rate limit is raised so only the dedicated rate-limit
 * tests exercise it. Tests use unique aliases and URLs, so they stay independent while sharing
 * the cached context.
 */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:it-${random.uuid};DB_CLOSE_DELAY=-1",
        "shortener.rate-limit.creates-per-minute=1000000"
})
@AutoConfigureMockMvc
@Import(TestSupportConfig.class)
public abstract class IntegrationTest {

    @Autowired
    protected MockMvc mvc;

    @Autowired
    protected ObjectMapper json;

    @Autowired
    protected MutableClock clock;

    @Autowired
    protected StubHostResolver resolver;

    @Autowired
    protected LinkRepository repository;

    @BeforeEach
    void resetDoubles() {
        clock.set(MutableClock.START);
        resolver.answers.clear();
        resolver.failing.clear();
    }

    protected static String uniqueAlias(String prefix) {
        return prefix + "-" + Long.toString(ThreadLocalRandom.current().nextLong(Long.MAX_VALUE), 36);
    }

    protected ResultActions postLink(Map<String, ?> body) throws Exception {
        return mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content(json.writeValueAsString(body)));
    }

    /** Creates a link and returns the parsed 201 response (code, shortPath, managementToken). */
    protected JsonNode create(String url, String alias, String expiresAt) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("url", url);
        if (alias != null) {
            body.put("alias", alias);
        }
        if (expiresAt != null) {
            body.put("expiresAt", expiresAt);
        }
        String response = postLink(body).andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        return json.readTree(response);
    }

    protected JsonNode create(String url) throws Exception {
        return create(url, null, null);
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/support/MutableClock.java">
package com.example.shortener.support;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;

/** A clock tests can set and advance, so expiry boundaries are exact rather than timing-dependent. */
public class MutableClock extends Clock {

    public static final Instant START = Instant.parse("2030-01-01T00:00:00Z");

    private volatile Instant now = START;

    public void set(Instant instant) {
        this.now = instant;
    }

    public void advance(Duration duration) {
        this.now = now.plus(duration);
    }

    @Override
    public Instant instant() {
        return now;
    }

    @Override
    public ZoneId getZone() {
        return ZoneOffset.UTC;
    }

    @Override
    public Clock withZone(ZoneId zone) {
        return this;
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/support/StubHostResolver.java">
package com.example.shortener.support;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;

import com.example.shortener.service.HostResolver;

/**
 * Deterministic DNS: IP literals are parsed (no lookup happens for literals), names listed in
 * {@link #answers} resolve as configured, names in {@link #failing} fail, and any other name
 * resolves to a single public address. Tests never touch real DNS.
 */
public class StubHostResolver implements HostResolver {

    public static final String PUBLIC_IP = "93.184.216.34";
    private static final Pattern IP_LITERAL = Pattern.compile("[0-9.]+|.*:.*");

    public final Map<String, List<String>> answers = new ConcurrentHashMap<>();
    public final Map<String, Boolean> failing = new ConcurrentHashMap<>();

    @Override
    public InetAddress[] resolve(String host) throws UnknownHostException {
        if (IP_LITERAL.matcher(host).matches()) {
            return new InetAddress[] {InetAddress.getByName(host)};
        }
        if (failing.containsKey(host)) {
            throw new UnknownHostException(host);
        }
        List<String> ips = answers.getOrDefault(host, List.of(PUBLIC_IP));
        InetAddress[] out = new InetAddress[ips.size()];
        for (int i = 0; i < ips.size(); i++) {
            out[i] = InetAddress.getByName(ips.get(i)); // literals only: no DNS
        }
        return out;
    }
}
</file>

<file path="url-shortener/src/test/java/com/example/shortener/support/TestSupportConfig.java">
package com.example.shortener.support;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/**
 * Replaces the production clock and DNS resolver with controllable test doubles. Each double is
 * the primary bean of its type (MutableClock is a Clock, StubHostResolver a HostResolver).
 */
@TestConfiguration
public class TestSupportConfig {

    @Bean
    @Primary
    public MutableClock testClock() {
        return new MutableClock();
    }

    @Bean
    @Primary
    public StubHostResolver stubHostResolver() {
        return new StubHostResolver();
    }
}
</file>
</implementation_and_existing_tests>

<write_scope>
- url-shortener/src/test/**
</write_scope>

## Output schema

```json
{
  "properties": {
    "summary": {
      "type": "string"
    },
    "files": {
      "items": {
        "properties": {
          "path": {
            "type": "string"
          },
          "content": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "content"
        ],
        "type": "object",
        "additionalProperties": false
      },
      "type": "array"
    },
    "decisions": {
      "items": {
        "properties": {
          "topic": {
            "type": "string"
          },
          "choice": {
            "type": "string"
          },
          "rationale": {
            "type": "string"
          }
        },
        "required": [
          "topic",
          "choice",
          "rationale"
        ],
        "type": "object",
        "additionalProperties": false
      },
      "type": "array"
    }
  },
  "required": [
    "summary",
    "files",
    "decisions"
  ],
  "type": "object",
  "additionalProperties": false
}
```
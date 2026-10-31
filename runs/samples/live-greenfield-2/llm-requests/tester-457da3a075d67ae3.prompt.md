# Session request: tester

Write the response as JSON matching the schema to:
`runs/live-greenfield-2/llm-requests/tester-457da3a075d67ae3.response.json`
(or use `orch respond runs/live-greenfield-2/llm-requests/tester-457da3a075d67ae3.request.json ...`)

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
    "Given a valid HTTP or HTTPS URL and no optional fields, when a client POSTs it to /api/links, then the service returns 201 with an 8-character code, a relative shortPath, and a management token shown only in that response.",
    "Given a valid custom alias and future expiry, when a client creates the link, then the service returns 201 and the metadata contains the alias, original URL, creation timestamp, and normalized UTC expiry timestamp.",
    "Given a custom alias shorter than 3 characters, longer than 32 characters, containing disallowed characters, or reserved for a service path, when a client creates a link, then the service returns 400.",
    "Given an alias already assigned to an active link or tombstone, when a client creates a link with that alias, then the service returns 409 Conflict.",
    "Given an invalid URL, a URL over 2,048 characters, a non-HTTP(S) scheme, localhost, or a host that is or resolves to a prohibited IPv4 or IPv6 address, when a client creates a link, then the service rejects it with HTTP 400 and does not create a link.",
    "Given a hostname that fails DNS resolution or resolves to any prohibited address among its results, when a client creates a link, then the service rejects it; after a link is created, the service does not fetch its destination.",
    "Given an active, unexpired link, when a client GETs /{code}, then the service returns 302 with the original URL in Location and Cache-Control: no-store.",
    "Given an expired link, when a client GETs /{code}, then the service returns 410 and does not redirect; when a client GETs /api/links/{code}, then the service still returns its public metadata.",
    "Given an unknown or deleted code, when a client GETs /{code} or GETs /api/links/{code}, then the service returns 404.",
    "Given an active link, when a client GETs /api/links/{code} without credentials, then the service returns HTTP 200 with the original URL, created timestamp, and expiry value.",
    "Given an active link, when a client DELETEs /api/links/{code} with its management token, then the service returns 204, erases the destination, and retains a tombstone reserving the code.",
    "Given a missing or invalid management token for an active link deletion, when a client sends DELETE, then the service returns 401 or 403 respectively and does not delete the link.",
    "Given a deleted code, when a client visits it, then the service returns 404; when a client attempts to create a link using that alias, then the service returns 409.",
    "Given 20 create requests from one client IP within the configured minute, when that IP sends a further create request while limited, then the service returns 429 with Retry-After; a service restart resets the in-memory limit.",
    "Given a created link or tombstone, when the service restarts using the same ./data store, then the link or reserved tombstone remains available and Flyway migrations have been applied.",
    "Given the service and H2 store are available, when an operations client GETs /health, then it receives HTTP 200; when persistence is unavailable, then it receives HTTP 503.",
    "Given the automated redirect latency test, when it performs 1,000 sequential warm-up requests followed by 1,000 measured requests from a single client on the local machine, then the measured in-process p99 is below 50 ms.",
    "Given the automated test suite, when it runs, then it exercises every functional requirement and the specified important success and failure paths."
  ],
  "ambiguities": [
    {
      "question": "What characters, length limits, and case-sensitivity rules apply to custom aliases?",
      "rationale": "Decided by a human: Apply the provided alias constraints and reserve every service route so aliases cannot shadow endpoints.",
      "resolution": "Custom aliases are 3-32 characters from [A-Za-z0-9_-], case-sensitive (consistent with generated codes). Reserved words are rejected: api, health, links (and any path the service itself uses).",
      "source": "assumption"
    },
    {
      "question": "What rate limit applies to link creation, over what interval, and how are clients identified (for example, by IP address)?",
      "rationale": "Decided by a human: The threshold, interval, response, storage, and library are binding; a 20-token bucket and counting all create requests are conventional abuse-resistant interpretations.",
      "resolution": "20 link creations per minute per client IP address. Exceeding it returns 429 Too Many Requests with a Retry-After header. Limits are held in memory (Bucket4j); a restart resets them. Interpret this as a bucket with capacity 20 refilled at 20 per minute; count requests to the create endpoint, including rejected attempts.",
      "source": "assumption"
    },
    {
      "question": "Who is allowed to fetch metadata or delete a link, and is authentication or authorization required?",
      "rationale": "Decided by a human: Implement public metadata and token-based deletion without user accounts, and persist no plaintext management token.",
      "resolution": "Metadata (GET) is public. Creating a link returns a one-time management token; DELETE requires that token (e.g. an X-Management-Token header), so only the creator can delete. No user accounts in v1. Store only a hash of the token, never the token itself.",
      "source": "assumption"
    },
    {
      "question": "Must links survive service restarts, and where should local link data be stored?",
      "rationale": "Decided by a human: Use the specified local H2 file store and Flyway migrations as the persistence design.",
      "resolution": "Yes, links must survive restarts. Use file-based H2 under ./data with Flyway-managed schema migrations.",
      "source": "assumption"
    },
    {
      "question": "Precisely which destinations count as malicious or internal, and should validation cover DNS-resolved addresses, IPv4, IPv6, and address changes over time?",
      "rationale": "Decided by a human: Enforce the specified schemes, length, address classes, one-time DNS check, and no-fetch limitation.",
      "resolution": "Accept only http/https URLs up to 2048 characters. Reject localhost and any host that is, or resolves to, a loopback, private, link-local, unique-local or multicast address (IPv4 and IPv6), checked once at creation. Re-pointing DNS after creation is an accepted, documented limitation: the service never fetches the URL.",
      "source": "assumption"
    },
    {
      "question": "What traffic volume, concurrency, measurement window, and runtime conditions define the p99 latency target?",
      "rationale": "Decided by a human: Use the specified test scope and treat the result as indicative rather than a production guarantee.",
      "resolution": "Measured in-process by an automated test: 1,000 redirect requests after a warm-up, single client, local machine, asserting p99 < 50 ms. Documented as an indicative check, not a production SLO.",
      "source": "assumption"
    },
    {
      "question": "After deletion, may a short code or custom alias be reused for a new link?",
      "rationale": "Decided by a human: Retain tombstones, erase the destination, and permanently reserve deleted codes and aliases.",
      "resolution": "No. Codes and custom aliases are never reused. Deleting a link keeps a tombstone record that reserves the code and erases the destination URL; a deleted code returns 404 like an unknown one, and creating a link with a deleted alias returns 409 Conflict.",
      "source": "assumption"
    },
    {
      "question": "What short-code length and alphabet should generated codes use?",
      "rationale": "The requirement leaves generated-code format open; an 8-character URL-safe code provides a practical namespace, and retrying collisions is a standard low-risk implementation.",
      "resolution": "Use 8-character generated codes from [A-Za-z0-9_-], case-sensitive. Regenerate a code if it collides with an active code, tombstone, or service route.",
      "source": "assumption"
    },
    {
      "question": "What redirect status code should the service return (301 vs 302)?",
      "rationale": "A temporary redirect is safer because links can expire or be deleted; preventing caching helps those changes take effect for subsequent visits.",
      "resolution": "Return 302 Found and include Cache-Control: no-store.",
      "source": "assumption"
    },
    {
      "question": "What should happen when a custom alias is already taken?",
      "rationale": "A conflict response is the conventional way to report a unique-resource naming collision and is consistent with the human decision that deleted aliases remain reserved.",
      "resolution": "Return HTTP 409 Conflict for an alias assigned to either an active link or a tombstone.",
      "source": "assumption"
    },
    {
      "question": "What HTTP paths, payload fields, and successful response bodies should the v1 API use?",
      "rationale": "The requirement names the operations but not their contract; these conventional REST routes and explicit fields make the v1 API testable without adding capabilities.",
      "resolution": "Use POST /api/links with JSON fields `url`, optional `alias`, and optional `expiresAt`; return 201 with `code`, `shortPath`, and `managementToken`. Use GET /{code} for redirects, GET /api/links/{code} for metadata, DELETE /api/links/{code} for deletion, and GET /health for health. Metadata fields are `originalUrl`, `createdAt`, and `expiresAt`.",
      "source": "assumption"
    },
    {
      "question": "What format should expiry use, and how should an expiry at or before creation time be handled?",
      "rationale": "An explicit UTC instant is an unambiguous conventional timestamp format; rejecting a non-future expiry avoids creating a link that is already expired.",
      "resolution": "Use an ISO-8601 UTC instant in the `expiresAt` field, normalize returned timestamps to UTC, and reject an expiry at or before creation time with HTTP 400.",
      "source": "assumption"
    },
    {
      "question": "What response behavior should apply to unknown, deleted, expired, malformed, and unauthorized requests?",
      "rationale": "The requirement does not define error statuses; these standard distinctions make failures observable, while 410 distinguishes expiry from an unknown or deleted link.",
      "resolution": "Return HTTP 400 for malformed or invalid create input, 409 for a taken alias, 429 with Retry-After when rate-limited, 302 for an active redirect, 410 for an expired redirect, and 404 for an unknown or deleted code. Metadata for an expired non-deleted link returns 200; metadata for an unknown or deleted code returns 404. On deletion, return 401 for a missing token, 403 for an invalid token, 204 on success, and 404 for an unknown or deleted code.",
      "source": "assumption"
    },
    {
      "question": "Should the create response contain an absolute short URL, and how is its public origin determined?",
      "rationale": "The requirement does not define a canonical public origin; returning a relative path avoids trusting request Host or proxy headers and needs no deployment configuration.",
      "resolution": "Return the relative `shortPath` and code, not an absolute URL; clients combine the path with the service origin they already use.",
      "source": "assumption"
    },
    {
      "question": "How should the management token be generated, exposed, and validated?",
      "rationale": "High-entropy random bearer tokens and one-time display with hash-only storage are conventional safeguards for a token that authorizes deletion.",
      "resolution": "Generate a cryptographically random 256-bit token, encode it as unpadded base64url, return it only in the creation response, and store a SHA-256 hash. Accept it in X-Management-Token and keep it valid until successful deletion; do not persist or log the plaintext token.",
      "source": "assumption"
    },
    {
      "question": "What should happen if DNS resolution fails or returns both allowed and prohibited addresses during URL validation?",
      "rationale": "Failing closed is the low-risk interpretation of the requirement to reject hosts that resolve to prohibited destinations.",
      "resolution": "Fail closed: reject the URL if resolution fails, times out, yields no usable address, or any returned address is prohibited.",
      "source": "assumption"
    },
    {
      "question": "How should the service identify a client IP when requests may include forwarding headers?",
      "rationale": "The service has no specified proxy deployment; using the peer address avoids spoofable client-supplied headers and is a safe local default.",
      "resolution": "Use the network peer address by default and do not trust forwarding headers unless a trusted-proxy configuration is explicitly provided.",
      "source": "assumption"
    },
    {
      "question": "What does the health endpoint check?",
      "rationale": "Checking both the application and the persistence store is a conventional operational health check for a service whose link operations depend on that store.",
      "resolution": "Return HTTP 200 with an UP status when the service and H2 store are available; return HTTP 503 otherwise.",
      "source": "assumption"
    },
    {
      "question": "What qualifies as meaningful automated test coverage?",
      "rationale": "Behavior-focused coverage directly verifies the requested capabilities without inventing an arbitrary percentage threshold.",
      "resolution": "Tests must exercise every functional requirement and the important validation, authorization, expiry, rate-limit, persistence, and redirect failure paths; no numeric coverage percentage is required.",
      "source": "assumption"
    },
    {
      "question": "How many requests should the latency test use for warm-up, and should measured requests be concurrent?",
      "rationale": "The human decision specifies a warm-up and a single client but not its size or concurrency; a fixed sequential warm-up makes the test repeatable and allows runtime initialization.",
      "resolution": "Use 1,000 sequential warm-up requests followed by the 1,000 measured requests from a single client.",
      "source": "assumption"
    }
  ],
  "clarifications": [
    {
      "answer": "Custom aliases are 3-32 characters from [A-Za-z0-9_-], case-sensitive (consistent with generated codes). Reserved words are rejected: api, health, links (and any path the service itself uses).",
      "question": "What characters, length limits, and case-sensitivity rules apply to custom aliases?"
    },
    {
      "answer": "20 link creations per minute per client IP address. Exceeding it returns 429 Too Many Requests with a Retry-After header. Limits are held in memory (Bucket4j); a restart resets them.",
      "question": "What rate limit applies to link creation, over what interval, and how are clients identified (for example, by IP address)?"
    },
    {
      "answer": "Metadata (GET) is public. Creating a link returns a one-time management token; DELETE requires that token (e.g. an X-Management-Token header), so only the creator can delete. No user accounts in v1. Store only a hash of the token, never the token itself.",
      "question": "Who is allowed to fetch metadata or delete a link, and is authentication or authorization required?"
    },
    {
      "answer": "Yes, links must survive restarts. Use file-based H2 under ./data with Flyway-managed schema migrations.",
      "question": "Must links survive service restarts, and where should local link data be stored?"
    },
    {
      "answer": "Accept only http/https URLs up to 2048 characters. Reject localhost and any host that is, or resolves to, a loopback, private, link-local, unique-local or multicast address (IPv4 and IPv6), checked once at creation. Re-pointing DNS after creation is an accepted, documented limitation: the service never fetches the URL.",
      "question": "Precisely which destinations count as malicious or internal, and should validation cover DNS-resolved addresses, IPv4, IPv6, and address changes over time?"
    },
    {
      "answer": "Measured in-process by an automated test: 1,000 redirect requests after a warm-up, single client, local machine, asserting p99 < 50 ms. Documented as an indicative check, not a production SLO.",
      "question": "What traffic volume, concurrency, measurement window, and runtime conditions define the p99 latency target?"
    },
    {
      "answer": "No. Codes and custom aliases are never reused. Deleting a link keeps a tombstone record that reserves the code and erases the destination URL; a deleted code returns 404 like an unknown one, and creating a link with a deleted alias returns 409 Conflict.",
      "question": "After deletion, may a short code or custom alias be reused for a new link?"
    }
  ],
  "functional": [
    {
      "id": "FR1",
      "text": "Create a link with POST /api/links using a JSON body with required `url` and optional `alias` and `expiresAt` fields. Return HTTP 201 with the code, relative `shortPath`, and a management token that is returned only in the creation response. Generated codes are 8 characters from `[A-Za-z0-9_-]`, case-sensitive. Custom aliases are 3\u201332 characters from `[A-Za-z0-9_-]`, case-sensitive; reject reserved service paths and invalid aliases with HTTP 400. Reject a custom alias already assigned to an active or tombstoned link with HTTP 409."
    },
    {
      "id": "FR2",
      "text": "Accept an optional future expiry timestamp in UTC. At or after that instant, do not redirect the link; return HTTP 410 Gone. Expiry does not delete the link or prevent public metadata retrieval."
    },
    {
      "id": "FR3",
      "text": "GET /{code} redirects an active, unexpired link to its original URL using HTTP 302 Found and a Location header. Do not cache redirect responses. Return HTTP 410 Gone for expired links and HTTP 404 Not Found for unknown or deleted codes."
    },
    {
      "id": "FR4",
      "text": "GET /api/links/{code} returns public metadata for a non-deleted link: original URL, creation timestamp, and expiry timestamp (null when no expiry is set). Return HTTP 404 Not Found for unknown or deleted codes. Expired links remain available through this endpoint."
    },
    {
      "id": "FR5",
      "text": "DELETE /api/links/{code} requires the link's management token in the X-Management-Token header. Return HTTP 204 No Content on successful deletion; return HTTP 401 for a missing token, HTTP 403 for an invalid token, and HTTP 404 for an unknown or already-deleted code. Deletion retains a tombstone reserving the code and erases the destination URL; neither generated codes nor custom aliases are reused. Store only a hash of the management token, never the plaintext token."
    },
    {
      "id": "FR6",
      "text": "GET /health provides an operations health check, returning HTTP 200 when the service and its persistence store are available and HTTP 503 otherwise."
    }
  ],
  "goal": "Provide a locally runnable HTTP service that creates shareable short links for validated HTTP/HTTPS URLs and redirects visitors to their destinations. Provide public link metadata, token-authorized deletion, expiry handling, and an operations health endpoint.",
  "non_functional": [
    {
      "id": "NFR1",
      "text": "An automated indicative performance check must measure 1,000 redirect requests after a warm-up, from a single client on the local machine, and assert p99 latency below 50 ms in-process. This check is not a production SLO."
    },
    {
      "id": "NFR2",
      "text": "Accept only syntactically valid HTTP or HTTPS URLs up to 2,048 characters. At creation, reject localhost and any host that is itself or resolves to a loopback, private, link-local, unique-local, or multicast IPv4 or IPv6 address. Check DNS-resolved addresses once at creation; DNS changes after creation are an accepted limitation. The service must not fetch destination URLs."
    },
    {
      "id": "NFR3",
      "text": "Protect link creation with an in-memory Bucket4j rate limit of 20 create requests per minute per client IP. Return HTTP 429 Too Many Requests with a Retry-After header when limited. A service restart resets the limit state."
    },
    {
      "id": "NFR4",
      "text": "Run locally with one command and no external infrastructure. Persist links and tombstones across restarts using file-based H2 under ./data, with Flyway-managed schema migrations."
    },
    {
      "id": "NFR5",
      "text": "Provide automated tests covering each functional flow and important failure paths, including URL and alias validation, expiry, deletion authorization, rate limiting, persistence across restart, and redirect latency."
    }
  ]
}
</approved_specification>

<test_plan>
{
  "test_cases": [
    {
      "check": "POST a valid HTTP URL without optional fields; assert HTTP 201, an 8-character code matching [A-Za-z0-9_-], a relative shortPath corresponding to the code, and a managementToken in the creation response.",
      "covers": "FR1 \u2014 generated-code creation response",
      "id": "TC-FR1-01",
      "level": "integration"
    },
    {
      "check": "POST a valid URL with a valid custom alias; assert HTTP 201 and that the response code and shortPath use that exact, case-sensitive alias.",
      "covers": "FR1 \u2014 custom alias creation",
      "id": "TC-FR1-02",
      "level": "integration"
    },
    {
      "check": "For aliases shorter than 3 characters, longer than 32 characters, containing characters outside [A-Za-z0-9_-], or equal to a reserved service path (including api, health, and links), assert HTTP 400 and no link is created.",
      "covers": "FR1 \u2014 custom alias validation",
      "id": "TC-FR1-03",
      "level": "integration"
    },
    {
      "check": "Create an active link with an alias, then POST another link using that alias; assert HTTP 409. Repeat with an alias reserved by a tombstone and assert HTTP 409.",
      "covers": "FR1 \u2014 alias conflicts",
      "id": "TC-FR1-04",
      "level": "integration"
    },
    {
      "check": "Make the code generator produce a code already assigned to an active link, then a code reserved by a tombstone, followed by an unused code; assert the service retries and returns only the unused code.",
      "covers": "FR1 \u2014 generated-code collision handling",
      "id": "TC-FR1-05",
      "level": "unit"
    },
    {
      "check": "Create a link expiring at a controlled future instant; assert redirect succeeds before that instant and returns HTTP 410 at and after it.",
      "covers": "FR2 \u2014 expiry boundary",
      "id": "TC-FR2-01",
      "level": "integration"
    },
    {
      "check": "POST a link with an expiry at or before its creation time and with a malformed expiry value; assert HTTP 400 and no link is created.",
      "covers": "FR2 \u2014 invalid expiry",
      "id": "TC-FR2-02",
      "level": "integration"
    },
    {
      "check": "After a link expires, GET /api/links/{code}; assert HTTP 200 and that its public metadata remains available.",
      "covers": "FR2 \u2014 expiry does not delete metadata",
      "id": "TC-FR2-03",
      "level": "integration"
    },
    {
      "check": "GET an active, unexpired code; assert HTTP 302, Location exactly equals the original URL, and Cache-Control includes no-store.",
      "covers": "FR3 \u2014 active redirect",
      "id": "TC-FR3-01",
      "level": "integration"
    },
    {
      "check": "GET a code whose expiry has passed; assert HTTP 410 and that no redirect Location is returned.",
      "covers": "FR3 \u2014 expired redirect",
      "id": "TC-FR3-02",
      "level": "integration"
    },
    {
      "check": "GET an unknown code and a previously deleted code; assert HTTP 404 for both and no redirect Location.",
      "covers": "FR3 \u2014 unknown and deleted redirects",
      "id": "TC-FR3-03",
      "level": "integration"
    },
    {
      "check": "GET metadata for an active link without credentials; assert HTTP 200 and the exact originalUrl, a creation timestamp, and expiresAt (null when no expiry was set).",
      "covers": "FR4 \u2014 public metadata",
      "id": "TC-FR4-01",
      "level": "integration"
    },
    {
      "check": "GET metadata for an unknown code and a deleted code; assert HTTP 404 for both.",
      "covers": "FR4 \u2014 metadata for unknown and deleted codes",
      "id": "TC-FR4-02",
      "level": "integration"
    },
    {
      "check": "DELETE an active link with its management token; assert HTTP 204 and an empty response body, then verify the destination is erased, redirects and metadata return 404, and creating the same alias returns 409.",
      "covers": "FR5 \u2014 authorized deletion and tombstone",
      "id": "TC-FR5-01",
      "level": "integration"
    },
    {
      "check": "DELETE an active link without X-Management-Token; assert HTTP 401 and verify the link still redirects to its original URL.",
      "covers": "FR5 \u2014 missing deletion token",
      "id": "TC-FR5-02",
      "level": "integration"
    },
    {
      "check": "DELETE an active link with an incorrect X-Management-Token; assert HTTP 403 and verify the link is not deleted.",
      "covers": "FR5 \u2014 invalid deletion token",
      "id": "TC-FR5-03",
      "level": "integration"
    },
    {
      "check": "DELETE an unknown code and a previously deleted code with a token header; assert HTTP 404 for both.",
      "covers": "FR5 \u2014 deletion of missing or already-deleted code",
      "id": "TC-FR5-04",
      "level": "integration"
    },
    {
      "check": "Create a link and inspect its persisted record and subsequent metadata/redirect responses; assert the plaintext management token is absent outside the create response and only a SHA-256 token hash is persisted.",
      "covers": "FR5 \u2014 token confidentiality and hash-only storage",
      "id": "TC-FR5-05",
      "level": "integration"
    },
    {
      "check": "With the Spring service and H2 store available, GET /health and assert HTTP 200 with status UP.",
      "covers": "FR6 \u2014 healthy service and persistence store",
      "id": "TC-FR6-01",
      "level": "integration"
    },
    {
      "check": "Make the persistence health check fail while the application remains running; GET /health and assert HTTP 503.",
      "covers": "FR6 \u2014 unavailable persistence store",
      "id": "TC-FR6-02",
      "level": "integration"
    },
    {
      "check": "Run 1,000 sequential redirect warm-up requests followed by 1,000 sequential measured requests from one in-process client on the local machine; calculate measured p99 and assert it is below 50 ms.",
      "covers": "NFR1 \u2014 indicative redirect latency",
      "id": "TC-NFR1-01",
      "level": "integration"
    },
    {
      "check": "POST malformed URLs, a URL longer than 2,048 characters, and URLs using non-HTTP(S) schemes; assert HTTP 400 for each and verify no link is created.",
      "covers": "NFR2 \u2014 URL syntax, scheme, and length",
      "id": "TC-NFR2-01",
      "level": "integration"
    },
    {
      "check": "Validate localhost and representative loopback, private, link-local, unique-local, and multicast IPv4 and IPv6 literals; assert every prohibited destination is rejected.",
      "covers": "NFR2 \u2014 prohibited localhost and address literals",
      "id": "TC-NFR2-02",
      "level": "unit"
    },
    {
      "check": "With a deterministic resolver, test a hostname resolving only to prohibited addresses and one resolving to a mix of allowed and prohibited addresses across IPv4 and IPv6; assert both are rejected.",
      "covers": "NFR2 \u2014 prohibited DNS results",
      "id": "TC-NFR2-03",
      "level": "unit"
    },
    {
      "check": "Make the resolver time out, fail, or return no usable addresses; assert URL validation fails closed.",
      "covers": "NFR2 \u2014 DNS resolution failure",
      "id": "TC-NFR2-04",
      "level": "unit"
    },
    {
      "check": "With a deterministic resolver returning only permitted addresses, validate syntactically valid HTTP and HTTPS URLs at or below the 2,048-character limit; assert they are accepted.",
      "covers": "NFR2 \u2014 valid public destination",
      "id": "TC-NFR2-05",
      "level": "unit"
    },
    {
      "check": "Create a link using a permitted test hostname and a spy on outbound HTTP clients; assert creation succeeds and no request is made to the destination.",
      "covers": "NFR2 \u2014 destination is never fetched",
      "id": "TC-NFR2-06",
      "level": "unit"
    },
    {
      "check": "From one peer IP, send 20 create requests within the configured minute and then a 21st; assert the first 20 are processed and the limited request returns HTTP 429 with a Retry-After header.",
      "covers": "NFR3 \u2014 per-IP creation limit",
      "id": "TC-NFR3-01",
      "level": "integration"
    },
    {
      "check": "Exhaust the creation bucket for one peer IP, then send a create request from a different peer IP and assert it is not limited; verify changing X-Forwarded-For alone does not change the bucket identity.",
      "covers": "NFR3 \u2014 IP isolation and forwarded-header handling",
      "id": "TC-NFR3-02",
      "level": "integration"
    },
    {
      "check": "Use an invalid create request among requests from one IP and verify it consumes a bucket token; after the limit is reached, restart the service and assert that IP can create again.",
      "covers": "NFR3 \u2014 rejected attempts count and restart reset",
      "id": "TC-NFR3-03",
      "level": "integration"
    },
    {
      "check": "Start the service with a temporary ./data H2 store, create a link and a tombstone, restart using the same store, and assert the active link and reserved tombstone remain available and Flyway reports its migrations applied.",
      "covers": "NFR4 \u2014 persistence and Flyway migrations",
      "id": "TC-NFR4-01",
      "level": "integration"
    },
    {
      "check": "Run the documented single local startup command in an environment without external infrastructure; assert the service starts, applies migrations to the file-based H2 store under ./data, and responds to an HTTP health request.",
      "covers": "NFR4 \u2014 local startup",
      "id": "TC-NFR4-02",
      "level": "integration"
    },
    {
      "check": "Run the automated service test suite and assert it includes executable tests for creation, validation, alias conflicts, expiry, redirects, metadata, authorized and rejected deletion, rate limiting, restart persistence, health, and redirect latency.",
      "covers": "NFR5 \u2014 automated functional and failure-path coverage",
      "id": "TC-NFR5-01",
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

<file path="url-shortener/src/main/java/com/example/shortener/api/ApiExceptionHandler.java">
package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.RateLimitedException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Every error is JSON {"error": <stable code>, "message": <human text>}. */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ApiException.class)
    ResponseEntity<ErrorResponse> api(ApiException e) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(e.getStatus());
        if (e instanceof RateLimitedException limited) {
            response.header(HttpHeaders.RETRY_AFTER, Long.toString(limited.getRetryAfterSeconds()));
        }
        return response.body(new ErrorResponse(e.getError(), e.getMessage()));
    }

    /** Malformed JSON, or a field of the wrong type such as an unparseable expiresAt. */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ErrorResponse> unreadable(HttpMessageNotReadableException e) {
        return ResponseEntity.badRequest()
                .body(new ErrorResponse("invalid_request", "request body is not valid JSON for this endpoint"));
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<ErrorResponse> mediaType(HttpMediaTypeNotSupportedException e) {
        return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE)
                .body(new ErrorResponse("unsupported_media_type", "use Content-Type: application/json"));
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
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.CreatedLink;
import jakarta.servlet.http.HttpServletRequest;
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

    public LinkController(LinkService links, CreateRateLimiter rateLimiter) {
        this.links = links;
        this.rateLimiter = rateLimiter;
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

    @DeleteMapping("/{code}")
    public ResponseEntity<Void> delete(@PathVariable String code,
                                       @RequestHeader(name = TOKEN_HEADER, required = false) String token) {
        links.delete(code, token);
        return ResponseEntity.noContent().build();
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/LinkDtos.java">
package com.example.shortener.api;

import java.time.Instant;

import com.example.shortener.domain.Link;

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

    public record ErrorResponse(String error, String message) {
    }
}
</file>

<file path="url-shortener/src/main/java/com/example/shortener/api/RedirectController.java">
package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.service.LinkService;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** The latency-sensitive path: one indexed lookup, then a 302. */
@RestController
public class RedirectController {

    private final LinkService links;

    public RedirectController(LinkService links) {
        this.links = links;
    }

    // Literal routes (/health, /api/...) take precedence over this pattern in Spring MVC.
    @GetMapping("/{code:[A-Za-z0-9_-]{3,32}}")
    public ResponseEntity<Void> redirect(@PathVariable String code) {
        URI destination = URI.create(links.resolveForRedirect(code));
        // no-store: links can expire or be deleted, so no client or proxy may cache the redirect
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(destination)
                .cacheControl(CacheControl.noStore())
                .build();
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

<file path="url-shortener/src/main/java/com/example/shortener/config/ShortenerProperties.java">
package com.example.shortener.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param dataDir    directory holding the file-based H2 database
 * @param rateLimit  link-creation rate limit per client IP
 * @param codeLength length of generated short codes
 */
@ConfigurationProperties(prefix = "shortener")
public record ShortenerProperties(String dataDir, RateLimit rateLimit, int codeLength) {

    public record RateLimit(int createsPerMinute) {
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

import org.springframework.data.jpa.repository.JpaRepository;

public interface LinkRepository extends JpaRepository<Link, Long> {

    /** Includes tombstones: a deleted code is still "taken". */
    Optional<Link> findByCode(String code);

    boolean existsByCode(String code);
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

    public ApiException(HttpStatus status, String error, String message) {
        super(message);
        this.status = status;
        this.error = error;
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
import java.time.temporal.ChronoUnit;

import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Link lifecycle: create, resolve for redirect, read metadata, delete into a tombstone. */
@Service
public class LinkService {

    static final int MAX_CODE_ATTEMPTS = 10;

    private final LinkRepository repository;
    private final DestinationPolicy destinationPolicy;
    private final AliasPolicy aliasPolicy;
    private final CodeGenerator codeGenerator;
    private final TokenService tokenService;
    private final Clock clock;

    public LinkService(LinkRepository repository, DestinationPolicy destinationPolicy, AliasPolicy aliasPolicy,
                       CodeGenerator codeGenerator, TokenService tokenService, Clock clock) {
        this.repository = repository;
        this.destinationPolicy = destinationPolicy;
        this.aliasPolicy = aliasPolicy;
        this.codeGenerator = codeGenerator;
        this.tokenService = tokenService;
        this.clock = clock;
    }

    /** The plaintext management token is returned here and nowhere else. */
    public record CreatedLink(Link link, String managementToken) {
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
        Link link = findLive(code);
        if (link.isExpiredAt(now())) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        return link.getOriginalUrl();
    }

    /** Public metadata; expired links are still described, deleted ones are not. */
    @Transactional(readOnly = true)
    public Link metadata(String code) {
        return findLive(code);
    }

    @Transactional
    public void delete(String code, String managementToken) {
        Link link = findLive(code);
        if (managementToken == null || managementToken.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "missing_token", "X-Management-Token header is required");
        }
        if (!tokenService.matches(managementToken, link.getTokenHash())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "invalid_token", "management token does not match");
        }
        link.markDeleted(now());
        repository.save(link);
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

<file path="url-shortener/src/main/java/com/example/shortener/service/RateLimitedException.java">
package com.example.shortener.service;

import org.springframework.http.HttpStatus;

public class RateLimitedException extends ApiException {

    private final long retryAfterSeconds;

    public RateLimitedException(long retryAfterSeconds) {
        super(HttpStatus.TOO_MANY_REQUESTS, "rate_limited", "too many links created; retry later");
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public long getRetryAfterSeconds() {
        return retryAfterSeconds;
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

shortener:
  data-dir: ./data
  rate-limit:
    creates-per-minute: 20
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
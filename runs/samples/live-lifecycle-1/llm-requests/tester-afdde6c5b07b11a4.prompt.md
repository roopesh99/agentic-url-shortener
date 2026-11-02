# Session request: tester

Write the response as JSON matching the schema to:
`runs/live-lifecycle-1/llm-requests/tester-afdde6c5b07b11a4.response.json`
(or use `orch respond runs/live-lifecycle-1/llm-requests/tester-afdde6c5b07b11a4.request.json ...`)

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
    "Given an active link and a valid management token, when the owner submits a future `expiresAt`, the request returns HTTP 200 with metadata showing that expiry; subsequent redirects use the updated expiry immediately.",
    "Given an active link and a valid management token, when the owner submits `expiresAt: null`, the request returns HTTP 200 with metadata showing no expiry, and subsequent redirects are no longer limited by the removed expiry.",
    "Given a request with an omitted `expiresAt`, when the service processes it, the request is rejected with HTTP 400 and the link remains unchanged.",
    "Given a request without a valid management token, when the service processes it, the service returns its established authentication-failure response and leaves the link unchanged.",
    "Given an already expired link, when an authorized owner attempts to set or remove its expiry, the service returns HTTP 410 with error code `expired` and leaves the link unchanged.",
    "Given a link that has not expired, when an authorized owner submits an expiry at or before the current time, the service returns HTTP 400 with error code `invalid_expiry` and leaves the link unchanged.",
    "Given a deleted link, when an authorized owner attempts to change its expiry, the service returns HTTP 404 and makes no change.",
    "Given an authorized owner submits a valid future expiry far beyond any commonly expected near-term period, when the request is processed, the service accepts it subject to the same validation rules as link creation; no update-only maximum is applied.",
    "Given the new capability is released, when existing endpoints are exercised, their behavior remains unchanged.",
    "Before shipment, the machine-readable API definition and operator and API-client documentation describe the operation, authentication, request values, and relevant success and error behavior.",
    "Before shipment, a changelog entry is prepared and a release-readiness review is recorded as complete."
  ],
  "ambiguities": [
    {
      "question": "Can extending the expiry bring an already expired link back to life?",
      "rationale": "Decided by a human: This is the binding decision and defines the required behavior for expired and deleted links.",
      "resolution": "No. An expired link stays expired and cannot be brought back to life. Changing the expiry of a link that has already expired is rejected with 410 and error code expired (as redirects to expired links already respond), and the link is left unchanged. Deleted links cannot be changed either (404, as today).",
      "source": "assumption"
    },
    {
      "question": "Is there a maximum expiry, and if so, what is it?",
      "rationale": "Decided by a human: This is the binding decision; expiry updates must not introduce a limit absent from creation.",
      "resolution": "No maximum, consistent with link creation, which has none today. Adding a maximum only for updates would be inconsistent, and adding one to creation would change existing behaviour (NFR1).",
      "source": "assumption"
    },
    {
      "question": "What should happen if an owner sets an expiry at or before the current time on a link that has not yet expired?",
      "rationale": "Decided by a human: This is the binding decision for validation, error response, and mutation behavior.",
      "resolution": "Reject it with 400 and error code invalid_expiry (expiresAt must be in the future), exactly as link creation does, and leave the link unchanged. An owner who wants a link gone deletes it. This keeps one expiry rule everywhere and prevents an irreversible accidental expiry.",
      "source": "assumption"
    },
    {
      "question": "What HTTP method and route should expose the expiry-change operation?",
      "rationale": "PATCH is a conventional method for changing part of a resource and provides an additive contract without changing existing endpoint behavior; retaining the service's base path and versioning avoids introducing a competing API convention.",
      "resolution": "Add an additive `PATCH /links/{linkId}` operation, retaining any existing API base path or version prefix used by the service.",
      "source": "assumption"
    },
    {
      "question": "How should a request distinguish setting an expiry, removing it, and omitting an expiry value?",
      "rationale": "Reusing the creation field and parser keeps the API consistent; `null` is a conventional explicit representation for clearing a nullable value, while rejecting omission avoids treating an incomplete expiry-change request as a successful no-op.",
      "resolution": "Use the `expiresAt` field and the same timestamp format and parsing rules as link creation. A future timestamp sets the expiry; `null` removes it; an omitted `expiresAt` field is rejected with HTTP 400 and leaves the link unchanged.",
      "source": "assumption"
    },
    {
      "question": "What success response should an expiry-change request return?",
      "rationale": "A 200 response with the updated representation is a conventional response for a successful resource update and directly makes the required metadata visible to the client.",
      "resolution": "Return HTTP 200 with the updated link metadata, including the new expiry or the absence of an expiry.",
      "source": "assumption"
    },
    {
      "question": "How should the management token be sent, and what response should be used for a missing or invalid token?",
      "rationale": "Reusing established authentication handling is the lowest-risk way to enforce the stated token-holder restriction without changing existing security or API conventions.",
      "resolution": "Use the service's existing management-token authentication mechanism and its existing authentication-failure response; do not mutate the link when authentication fails.",
      "source": "assumption"
    },
    {
      "question": "What format and location should be used for the machine-readable API definition and operator and API-client documentation?",
      "rationale": "OpenAPI 3.x is a widely supported machine-readable API standard, while using the repository's existing documentation conventions minimizes duplication and inconsistency.",
      "resolution": "Use an OpenAPI 3.x definition and place it and the operator and API-client documentation in the service's established documentation locations and formats.",
      "source": "assumption"
    },
    {
      "question": "What form should the changelog entry and release-readiness review take?",
      "rationale": "Following existing release conventions is the conventional, low-risk approach and makes the required pre-release artifacts auditable without introducing a new process.",
      "resolution": "Use the repository's established changelog and release-review formats; record completion of the review before shipment, including the change's verification, compatibility, and documentation readiness.",
      "source": "assumption"
    }
  ],
  "clarifications": [
    {
      "answer": "No. An expired link stays expired and cannot be brought back to life. Changing the expiry of a link that has already expired is rejected with 410 and error code expired (as redirects to expired links already respond), and the link is left unchanged. Deleted links cannot be changed either (404, as today).",
      "question": "Can extending the expiry bring an already expired link back to life?"
    },
    {
      "answer": "No maximum, consistent with link creation, which has none today. Adding a maximum only for updates would be inconsistent, and adding one to creation would change existing behaviour (NFR1).",
      "question": "Is there a maximum expiry, and if so, what is it?"
    },
    {
      "answer": "Reject it with 400 and error code invalid_expiry (expiresAt must be in the future), exactly as link creation does, and leave the link unchanged. An owner who wants a link gone deletes it. This keeps one expiry rule everywhere and prevents an irreversible accidental expiry.",
      "question": "What should happen if an owner sets an expiry at or before the current time on a link that has not yet expired?"
    }
  ],
  "functional": [
    {
      "id": "FR1",
      "text": "The owner of an existing link can set a new expiry or remove its expiry."
    },
    {
      "id": "FR2",
      "text": "Only a holder of the link's management token can change that link's expiry."
    },
    {
      "id": "FR3",
      "text": "After a successful change, subsequent redirects use the new expiry immediately, and the link's metadata reports the new expiry or that no expiry is set."
    },
    {
      "id": "FR4",
      "text": "A change to the expiry of an already expired link is rejected with HTTP 410 and error code `expired`; the link remains unchanged and cannot be brought back to life by changing its expiry."
    },
    {
      "id": "FR5",
      "text": "For a link that has not expired, an expiry at or before the current time is rejected with HTTP 400 and error code `invalid_expiry`; the link remains unchanged."
    },
    {
      "id": "FR6",
      "text": "A deleted link cannot be changed; an expiry-change request for it is rejected with HTTP 404, consistent with current behavior."
    },
    {
      "id": "FR7",
      "text": "Expiry changes have no maximum expiry limit; future expiry values are subject to the same validation rules as link creation."
    }
  ],
  "goal": "Add an owner-authenticated way to set or remove a link's expiry after creation. Successful changes must immediately affect redirects and be reflected in link metadata, with existing endpoints retaining their behavior.",
  "non_functional": [
    {
      "id": "NFR1",
      "text": "Existing endpoints and their behavior remain unchanged; the expiry-change capability is additive."
    },
    {
      "id": "NFR2",
      "text": "The service API is described by a machine-readable definition, and documentation for operators and API clients describes the expiry-change capability."
    },
    {
      "id": "NFR3",
      "text": "A changelog entry and a recorded release-readiness review are prepared before the release ships."
    }
  ]
}
</approved_specification>

<approved_impact_analysis>
{
  "api_changes": [
    {
      "change": "Add an operation using the service's existing base path and code path parameter. Request: Content-Type application/json; required X-Management-Token header; body {\"expiresAt\": \"<ISO-8601 instant>\"} to set a future expiry or {\"expiresAt\": null} to remove it. Omission of expiresAt, malformed input, or a non-future timestamp returns HTTP 400; non-future timestamps use error code invalid_expiry. Success: HTTP 200 with the updated LinkMetadata representation, including expiresAt as the new instant or null. Errors: HTTP 401 missing_token, HTTP 403 invalid_token, HTTP 429 rate_limited when the existing shared wrong-token limit is exceeded, HTTP 404 not_found for unknown or deleted links, and HTTP 410 expired for an already expired link. Error bodies retain the existing {error, message} format. No maximum expiry is added. Existing endpoints keep their current contracts unless the specification says otherwise; this operation is additive.",
      "method": "PATCH",
      "path": "/api/links/{code}"
    }
  ],
  "change_requests": [
    "Keep the technical plan unchanged. Align documentation and release files with the workflow's fixed locations: the API definition is url-shortener/openapi.yaml; operator and API-client documentation are url-shortener/README.md and url-shortener/docs/api.md (no separate guides); the design note is url-shortener/docs/design.md; the release-readiness record is url-shortener/docs/releases/<version>.md; the changelog is url-shortener/CHANGELOG.md.",
    "Keep this revision's file locations and everything else unchanged, and restore two items from v1: (1) modify ManagementTokenRateLimitTest to verify that wrong tokens on PATCH /api/links/{code} count toward the shared management-token throttle; (2) the concurrency test must cover an expiry update concurrent with click recording (redirect path) as well as with deletion."
  ],
  "data_changes": [
    "No schema change is needed: links.expires_at already exists and is nullable, which supports both setting and removing an expiry.",
    "No migration file is required. Existing migrations V1 and V2 remain immutable; any future schema changes must use a new, higher-numbered migration."
  ],
  "data_flows": [
    "PATCH parses the request while preserving whether expiresAt was supplied. The controller rejects an omitted field; explicit null reaches the service as a request to clear expiry.",
    "LinkService obtains the link with the existing pessimistic lockByCode operation, checks that it is live, authenticates using the stored token hash and existing constant-time token comparison, then rejects an already expired link with 410 or a non-future requested expiry with 400. A valid change is saved in the transaction; no token or token hash is returned.",
    "The updated expires_at is committed to the existing links row. The PATCH response is built from that updated link, and the existing metadata and redirect lookup paths read the persisted value; no cache or separate expiry store is introduced.",
    "Redirect lookup remains a database lookup with no new work or lock on its read path. Click recording remains separate and best-effort; it uses the existing link-row lock, so a concurrent expiry update can serialize with it. Keep the update transaction short so this contention does not unnecessarily delay redirects, and preserve RedirectController's behavior of serving the redirect if click recording fails."
  ],
  "impacted": [
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/api/LinkController.java",
      "reason": "FR1\u2013FR3, FR2: add the PATCH route, return updated metadata, and use the existing token-failure throttle."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/api/LinkDtos.java",
      "reason": "FR1, FR3: add an update request type that distinguishes an omitted expiresAt from an explicit null, while reusing the existing metadata response."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/domain/Link.java",
      "reason": "FR1, FR3: provide a way to update the existing nullable expiresAt field."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/domain/LinkRepository.java",
      "reason": "FR1, FR3: document the existing row-locking operation's use by expiry updates as well as click recording and deletion."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/service/ClickRecorder.java",
      "reason": "FR3: keep the row-locking documentation accurate when expiry updates also serialize with click recording."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/service/LinkService.java",
      "reason": "FR1\u2013FR7: implement token-authorized, transactional expiry updates with the required deleted, expired, and future-expiry validation."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/main/java/com/example/shortener/service/ManagementTokenRateLimiter.java",
      "reason": "FR2: update the limiter documentation to include expiry updates in the shared stats/delete management-token throttle."
    },
    {
      "kind": "create",
      "path": "url-shortener/src/test/java/com/example/shortener/api/LinkExpiryUpdateTest.java",
      "reason": "FR1\u2013FR7, NFR1: exercise the new HTTP contract, validation, authentication, metadata, and redirect behavior."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/api/ClickDeletionRaceTest.java",
      "reason": "FR3: add concurrency coverage for expiry updates against click recording on the redirect path, as well as against deletion."
    },
    {
      "kind": "modify",
      "path": "url-shortener/src/test/java/com/example/shortener/api/ManagementTokenRateLimitTest.java",
      "reason": "FR2: verify wrong tokens on PATCH count toward the shared management-token throttle."
    },
    {
      "kind": "create",
      "path": "url-shortener/openapi.yaml",
      "reason": "NFR2: define the PATCH operation, authentication, request values, response metadata, and relevant errors in OpenAPI 3.x."
    },
    {
      "kind": "create",
      "path": "url-shortener/README.md",
      "reason": "NFR2: document the expiry-change capability for operators at the workflow-required location."
    },
    {
      "kind": "create",
      "path": "url-shortener/docs/api.md",
      "reason": "NFR2: document the operation, authentication, request values, and success and error behavior for API clients."
    },
    {
      "kind": "create",
      "path": "url-shortener/docs/design.md",
      "reason": "FR3\u2013FR7: record the update, locking, and expiry-validation design at the workflow-required location."
    },
    {
      "kind": "create",
      "path": "url-shortener/CHANGELOG.md",
      "reason": "NFR3: prepare a changelog entry at the workflow-required location."
    },
    {
      "kind": "create",
      "path": "url-shortener/docs/releases/1.0.0-SNAPSHOT.md",
      "reason": "NFR3: record the release-readiness review for the current pom.xml version at the workflow-required location."
    }
  ],
  "risks": [
    {
      "detection": "LinkExpiryUpdateTest should assert omission returns 400 and that the stored expiry is unchanged, while explicit null succeeds and reports null.",
      "mitigation": "Use an update DTO that records field presence separately from its nullable value, and reject omission before calling the service.",
      "risk": "A request implementation that treats both an omitted expiresAt and explicit null as Java null could accidentally clear expiry on an incomplete request."
    },
    {
      "detection": "LinkExpiryUpdateTest should cover an authorized update to an expired link (410 expired), a timestamp at or before now (400 invalid_expiry), and unchanged persisted state for both.",
      "mitigation": "Under the row lock, reject an already expired link before mutation; otherwise require a non-null requested expiry to be strictly after the service clock, using the same microsecond truncation and future rule as creation.",
      "risk": "An expired link could be revived, or a past expiry could be persisted, if validation order or the expiry boundary differs from creation and redirect behavior."
    },
    {
      "detection": "The expanded ClickDeletionRaceTest should exercise expiry update concurrent with click recording and with deletion, checking the final expiry, click, and tombstone invariants.",
      "mitigation": "Reuse lockByCode and the existing transaction; click recording and deletion already use the corresponding link-row lock. Do not add a second persistence path.",
      "risk": "An update racing deletion or click recording could observe or write inconsistent link state."
    },
    {
      "detection": "LinkExpiryUpdateTest should assert missing and wrong tokens leave state unchanged; ManagementTokenRateLimitTest should show wrong PATCH tokens contribute to the shared limit.",
      "mitigation": "Use the same authorization and withTokenThrottle patterns as the existing stats and delete operations; do not mutate before authorization.",
      "risk": "Incorrect token handling could permit an unauthorized update or make PATCH token guessing bypass the established shared rate limit."
    },
    {
      "detection": "LinkExpiryUpdateTest should set a far-future expiry successfully; LinkCreationTest continues to protect existing creation validation.",
      "mitigation": "Apply only the existing creation validation rule that an expiry must be in the future; do not add an update-only maximum or alter creation.",
      "risk": "Adding a maximum expiry only on updates, or changing creation behavior to impose one, would violate the specified compatibility rule."
    },
    {
      "detection": "Run LinkCreationTest, LinkLifecycleTest, LinkStatsTest, ErrorContractAndHeadersTest, and ClickFailureIsolationTest alongside the new endpoint tests.",
      "mitigation": "Keep the route additive, reuse existing metadata/error/token conventions, and leave existing create, metadata, stats, delete, and redirect behavior untouched.",
      "risk": "Changes to shared DTOs, authentication, or persistence behavior could unintentionally alter existing endpoint contracts."
    },
    {
      "detection": "Review all required artifacts against the endpoint and its tests before shipment, including completion of the checklist in docs/releases/1.0.0-SNAPSHOT.md.",
      "mitigation": "Keep OpenAPI, README, API-client documentation, changelog, design note, and release-readiness record aligned with the implemented contract; record compatibility, verification, and documentation readiness in the release record.",
      "risk": "Documentation or the release record could disagree with actual status codes, authentication, or the shipped API definition."
    }
  ],
  "test_strategy": [
    "Add LinkExpiryUpdateTest using the existing IntegrationTest support and controllable clock. Cover setting a future expiry and seeing it in the 200 response and metadata; clearing with explicit null; redirect behavior before and after changes; omitted field rejection; missing and invalid token responses with unchanged state; expired-link 410 expired; at-or-before-now 400 invalid_expiry; deleted-link 404; and a far-future accepted value.",
    "Modify ClickDeletionRaceTest to cover an expiry update concurrent with click recording as well as the existing update/deletion-relevant locking behavior; assert serialization preserves the intended final link state and click invariants.",
    "Modify ManagementTokenRateLimitTest to send wrong tokens to PATCH /api/links/{code} and prove those failures count in the same per-peer limit as stats and delete, while valid tokens remain usable.",
    "Existing LinkLifecycleTest protects redirect expiry boundaries, public metadata, deleted-link behavior, and token-authorized deletion; LinkCreationTest protects the existing timestamp format and creation validation.",
    "Existing ErrorContractAndHeadersTest protects standard error bodies, existing endpoint contracts, and security headers; ClickFailureIsolationTest protects best-effort click persistence and redirect availability.",
    "Existing LinkStatsTest and ClickDeletionRaceTest protect click behavior and deletion consistency; ClickPersistenceAndUpgradeTest and PersistenceRestartTest protect persisted data and migration compatibility.",
    "Existing RedirectLatencyTest protects the redirect hot path's latency expectation. Run it with the new tests to detect accidental extra redirect-path work.",
    "Before shipment, manually verify the OpenAPI definition and operator/API-client docs against the implemented request and response behavior, and complete the release-readiness review."
  ]
}
</approved_impact_analysis>

<approved_api_definition>
openapi: 3.0.3
info:
  title: URL Shortener API
  version: 1.0.0-SNAPSHOT
  description: HTTP API for creating, managing, inspecting, and redirecting short links.
servers:
  - url: /
tags:
  - name: Links
    description: Link creation and management.
  - name: Redirects
    description: Public short-link redirects.
  - name: Operations
    description: Public service health.
paths:
  /api/links:
    post:
      tags: [Links]
      operationId: createLink
      summary: Create a short link
      description: Creates a link and returns its one-time plaintext management token. Creation requests are limited per client peer address. expiresAt is optional; when provided it must be in the future. There is no maximum expiry.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateLinkRequest'
            example:
              url: https://example.com/article
              alias: article
              expiresAt: '2030-01-01T00:00:00Z'
      responses:
        '201':
          description: Link created.
          headers:
            Location:
              $ref: '#/components/headers/Location'
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CreateLinkResponse'
        '400':
          $ref: '#/components/responses/BadRequest'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '409':
          $ref: '#/components/responses/Conflict'
        '413':
          $ref: '#/components/responses/PayloadTooLarge'
        '415':
          $ref: '#/components/responses/UnsupportedMediaType'
        '429':
          $ref: '#/components/responses/RateLimited'
        '500':
          $ref: '#/components/responses/InternalError'
        '503':
          $ref: '#/components/responses/ServiceUnavailable'
  /api/links/{code}:
    parameters:
      - name: code
        in: path
        required: true
        description: Link code or custom alias.
        schema:
          type: string
    get:
      tags: [Links]
      operationId: getLinkMetadata
      summary: Get public link metadata
      description: Returns metadata for a live or expired link. Deleted and unknown links are not exposed.
      responses:
        '200':
          description: Link metadata.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LinkMetadata'
        '404':
          $ref: '#/components/responses/NotFound'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '413':
          $ref: '#/components/responses/PayloadTooLarge'
        '500':
          $ref: '#/components/responses/InternalError'
    patch:
      tags: [Links]
      operationId: updateLinkExpiry
      summary: Set or remove a link expiry
      description: |-
        Changes only the expiry of an existing link. Supply expiresAt as an ISO-8601 instant strictly in the future to set it, or explicit null to remove it. The field is required; omission is rejected with 400 and does not change the link. A non-future instant is rejected with 400 and error code invalid_expiry. No update-only maximum expiry is imposed.

        A missing management token returns 401 (missing_token); a wrong token returns 403 (invalid_token), or 429 (rate_limited) when the shared management-token failure limit is exceeded. These failures do not mutate the link. Unknown or deleted links return 404 (not_found). After token authorization, an already expired link returns 410 (expired) and cannot be revived. Successful changes return the updated public metadata. The update takes the existing link-row lock and is committed before the response; subsequent metadata reads and redirect lookups use the persisted expiry.
      security:
        - ManagementToken: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateLinkExpiryRequest'
            examples:
              setExpiry:
                summary: Set a future expiry
                value:
                  expiresAt: '2030-01-01T00:00:00Z'
              removeExpiry:
                summary: Remove the expiry
                value:
                  expiresAt: null
      responses:
        '200':
          description: Expiry updated; the returned metadata contains the new instant or null when expiry was removed.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LinkMetadata'
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '410':
          $ref: '#/components/responses/Expired'
        '413':
          $ref: '#/components/responses/PayloadTooLarge'
        '415':
          $ref: '#/components/responses/UnsupportedMediaType'
        '429':
          $ref: '#/components/responses/RateLimited'
        '500':
          $ref: '#/components/responses/InternalError'
    delete:
      tags: [Links]
      operationId: deleteLink
      summary: Delete a link
      description: Deletes a link into a tombstone. A valid management token is required. Expiry does not prevent deletion.
      parameters:
        - $ref: '#/components/parameters/OptionalManagementToken'
      responses:
        '204':
          description: Link deleted; no response body.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '413':
          $ref: '#/components/responses/PayloadTooLarge'
        '429':
          $ref: '#/components/responses/RateLimited'
        '500':
          $ref: '#/components/responses/InternalError'
  /api/links/{code}/stats:
    get:
      tags: [Links]
      operationId: getLinkStats
      summary: Get private link statistics
      description: Returns lifetime clicks, daily click counts for the current UTC day and previous 29 days, and the last click time. Expired links retain stats; deleted links do not. Wrong management tokens share the management-token throttle with deletion and expiry updates.
      parameters:
        - name: code
          in: path
          required: true
          description: Link code or custom alias.
          schema:
            type: string
        - $ref: '#/components/parameters/OptionalManagementToken'
      responses:
        '200':
          description: Link statistics.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StatsResponse'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '413':
          $ref: '#/components/responses/PayloadTooLarge'
        '429':
          $ref: '#/components/responses/RateLimited'
        '500':
          $ref: '#/components/responses/InternalError'
  /{code}:
    get:
      tags: [Redirects]
      operationId: redirectToDestination
      summary: Redirect to the original URL
      description: Resolves an active short link, records a click best-effort, and responds with a non-cacheable 302 redirect. Unknown or deleted codes return 404; expired links return 410. Click-recording failures do not prevent the redirect.
      parameters:
        - name: code
          in: path
          required: true
          description: Short code; the route matches 3–32 ASCII letters, digits, underscores, or hyphens.
          schema:
            type: string
            pattern: '^[A-Za-z0-9_-]{3,32}$'
      responses:
        '302':
          description: Redirect to the link destination.
          headers:
            Location:
              $ref: '#/components/headers/Location'
            Cache-Control:
              $ref: '#/components/headers/CacheControl'
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
        '404':
          $ref: '#/components/responses/NotFound'
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '410':
          $ref: '#/components/responses/Expired'
        '500':
          $ref: '#/components/responses/InternalError'
        '503':
          $ref: '#/components/responses/RedirectUnavailable'
  /health:
    get:
      tags: [Operations]
      operationId: getHealth
      summary: Check public service health
      description: Returns UP when the service can reach its database, otherwise DOWN with HTTP 503.
      responses:
        '200':
          description: Database is reachable.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthResponse'
              example:
                status: UP
        '405':
          $ref: '#/components/responses/MethodNotAllowed'
        '500':
          $ref: '#/components/responses/InternalError'
        '503':
          description: Database is unavailable.
          headers:
            X-Content-Type-Options:
              $ref: '#/components/headers/XContentTypeOptions'
            X-Frame-Options:
              $ref: '#/components/headers/XFrameOptions'
            Referrer-Policy:
              $ref: '#/components/headers/ReferrerPolicy'
            Content-Security-Policy:
              $ref: '#/components/headers/ContentSecurityPolicy'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthResponse'
              example:
                status: DOWN
components:
  securitySchemes:
    ManagementToken:
      type: apiKey
      in: header
      name: X-Management-Token
      description: Per-link secret returned only in the link-creation response. Required to update expiry.
  parameters:
    OptionalManagementToken:
      name: X-Management-Token
      in: header
      required: false
      description: Management token for the link. Omission produces 401 missing_token; an incorrect token produces 403 invalid_token unless the shared wrong-token limit is exceeded.
      schema:
        type: string
  headers:
    Location:
      description: Relative link metadata URI on creation, or absolute destination URI on redirect.
      schema:
        type: string
    CacheControl:
      description: Redirect responses are not cacheable.
      schema:
        type: string
        example: no-store
    RetryAfter:
      description: Seconds to wait before retrying.
      schema:
        type: string
        pattern: '^[0-9]+$'
    XContentTypeOptions:
      description: Security header present on every response.
      schema:
        type: string
        example: nosniff
    XFrameOptions:
      description: Security header present on every response.
      schema:
        type: string
        example: DENY
    ReferrerPolicy:
      description: Security header present on every response.
      schema:
        type: string
        example: no-referrer
    ContentSecurityPolicy:
      description: Security header present on every response.
      schema:
        type: string
        example: "default-src 'none'; frame-ancestors 'none'"
  schemas:
    CreateLinkRequest:
      type: object
      required: [url]
      properties:
        url:
          type: string
          description: Destination URL. Only http and https destinations are accepted, and the service rejects prohibited local or private destinations.
          maxLength: 2048
        alias:
          type: string
          nullable: true
          description: Optional custom code; 3–32 letters, digits, underscores, or hyphens, subject to reserved-name and uniqueness checks.
        expiresAt:
          type: string
          format: date-time
          nullable: true
          description: Optional expiry instant. When supplied, it must be in the future. No maximum expiry is imposed.
    CreateLinkResponse:
      type: object
      required: [code, shortPath, managementToken]
      properties:
        code:
          type: string
        shortPath:
          type: string
          example: /abc12345
        managementToken:
          type: string
          description: Plaintext management token; returned only at creation.
    UpdateLinkExpiryRequest:
      type: object
      required: [expiresAt]
      description: expiresAt is required. A future instant sets expiry; explicit null removes it. Omission is rejected.
      properties:
        expiresAt:
          type: string
          format: date-time
          nullable: true
          description: Future ISO-8601 instant to set, or null to remove expiry. Values at or before the current time are rejected with invalid_expiry.
    LinkMetadata:
      type: object
      required: [code, alias, originalUrl, createdAt, expiresAt]
      properties:
        code:
          type: string
        alias:
          type: string
          nullable: true
          description: The code when it is a custom alias; otherwise null.
        originalUrl:
          type: string
          description: Original destination URL.
        createdAt:
          type: string
          format: date-time
        expiresAt:
          type: string
          format: date-time
          nullable: true
          description: Expiry instant, or null when the link has no expiry.
    StatsResponse:
      type: object
      required: [totalClicks, dailyClicks, lastClickedAt]
      properties:
        totalClicks:
          type: integer
          format: int64
        dailyClicks:
          type: array
          description: Click counts for 30 UTC calendar days, oldest first, including zero-count days.
          items:
            $ref: '#/components/schemas/DailyClicksResponse'
        lastClickedAt:
          type: string
          format: date-time
          nullable: true
    DailyClicksResponse:
      type: object
      required: [date, clicks]
      properties:
        date:
          type: string
          format: date
        clicks:
          type: integer
          format: int64
    HealthResponse:
      type: object
      required: [status]
      properties:
        status:
          type: string
          enum: [UP, DOWN]
    ErrorResponse:
      type: object
      required: [error, message]
      properties:
        error:
          type: string
          description: Stable machine-readable error code.
        message:
          type: string
          description: Human-readable error message.
  responses:
    BadRequest:
      description: Bad request. Error codes include invalid_request, invalid_url, prohibited_destination, invalid_expiry, invalid_alias, and reserved_alias, depending on the operation and failure.
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    Unauthorized:
      description: Missing management token (missing_token).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    Forbidden:
      description: Incorrect management token (invalid_token).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    NotFound:
      description: Unknown or deleted link (not_found), or no matching resource.
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    MethodNotAllowed:
      description: Method is not allowed for this resource (method_not_allowed).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    Expired:
      description: Link has expired (expired).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    PayloadTooLarge:
      description: Request body exceeds the configured API body limit (payload_too_large).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    UnsupportedMediaType:
      description: Unsupported request media type (unsupported_media_type); use application/json.
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    Conflict:
      description: Requested alias is already in use (alias_taken).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    RateLimited:
      description: Too many requests or wrong management-token attempts (rate_limited). Retry-After gives the number of seconds to wait.
      headers:
        Retry-After:
          $ref: '#/components/headers/RetryAfter'
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    InternalError:
      description: Unexpected internal error (internal_error).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    ServiceUnavailable:
      description: Service cannot complete the request (service_unavailable or code_collision).
      headers:
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
    RedirectUnavailable:
      description: Link store could not serve a redirect (service_unavailable). Retry after the indicated delay.
      headers:
        Retry-After:
          $ref: '#/components/headers/RetryAfter'
        X-Content-Type-Options:
          $ref: '#/components/headers/XContentTypeOptions'
        X-Frame-Options:
          $ref: '#/components/headers/XFrameOptions'
        Referrer-Policy:
          $ref: '#/components/headers/ReferrerPolicy'
        Content-Security-Policy:
          $ref: '#/components/headers/ContentSecurityPolicy'
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'
</approved_api_definition>

<approved_design_notes>
## Components and change

`LinkController` gains `PATCH /api/links/{code}` under the existing `/api/links` base path. It delegates the update to `LinkService`, uses the existing management-token failure throttle, and returns the existing `LinkMetadata` representation. `LinkDtos` gains a request type that preserves the difference between an omitted `expiresAt` and explicit `null`. `Link` gains an expiry mutator; `LinkRepository.lockByCode` is reused for the update. Existing create, metadata, stats, delete, redirect, health, error handling, and filters retain their behavior.

## Data and schema

No schema or migration change is required: `links.expires_at` already stores nullable timestamps at microsecond precision. Expiry updates persist to that column; there is no cache, secondary expiry store, or maximum expiry. The plaintext management token is not returned by the update operation and the stored token hash is unchanged.

## Hot-path flows

**Expiry update:** parse the JSON while preserving field presence; reject omission before calling the service. In a short transaction, lock the link by code, return 404 for unknown or deleted links, authenticate with the existing constant-time token check, reject already expired links with 410 `expired`, and then validate any non-null requested expiry using the creation rule: truncate to microseconds and require it to be strictly after the service clock. Persist the new value (or null), commit, and build the response metadata from the updated link. Wrong-token failures continue through the shared management-token throttle. No mutation occurs for failed validation or authentication.

**Redirect and metadata:** redirect resolution remains the existing database lookup and expiry check, with no new lock or work on the redirect read path. After an update commits, later redirect and metadata lookups read the persisted expiry. Click recording remains best-effort in its own transaction and uses the existing row lock; updates therefore serialize with click recording and deletion. Preserve the redirect controller's behavior of serving the redirect if click recording fails.

## Non-functional requirements and verification

The route is additive and does not change creation limits or existing endpoint contracts. Keep update transactions short to limit lock contention. Cover set, clear, omission, auth failures, expired/deleted links, boundary/far-future validation, redirect behavior, shared throttling, and update races with click recording and deletion. Run existing lifecycle, creation, error/header, click-isolation, persistence, and redirect-latency tests. The API definition belongs at `url-shortener/openapi.yaml`; operator and client documentation at `url-shortener/README.md` and `url-shortener/docs/api.md`; changelog and release-readiness record at the workflow's specified locations.

## Rejected alternatives

- A separate expiry endpoint or a different base path would introduce a competing API convention; PATCH on the existing link resource is additive and matches the approved route.
- Treating omitted `expiresAt` as null would turn an incomplete request into an accidental expiry removal, so omission is rejected explicitly.
- Allowing an expired link to be revived conflicts with redirect expiry behavior; expired links stay expired and updates return 410.
- An update-only maximum, schema migration, cache, or separate persistence path adds inconsistency or complexity without need. Locking redirect resolution would also add avoidable work to the latency-sensitive read path.
</approved_design_notes>

<test_plan>
{
  "test_cases": [
    {
      "check": "PATCH an active link with a valid management token and future expiresAt; assert HTTP 200 and that the response metadata contains the requested expiry.",
      "covers": "FR1",
      "id": "TC-FR1-01",
      "level": "integration"
    },
    {
      "check": "PATCH an active link with expiresAt explicitly set to null; assert HTTP 200 and response metadata contains expiresAt: null.",
      "covers": "FR1",
      "id": "TC-FR1-02",
      "level": "integration"
    },
    {
      "check": "PATCH an active link with expiresAt omitted; assert HTTP 400 and verify the persisted expiry is unchanged.",
      "covers": "FR1",
      "id": "TC-FR1-03",
      "level": "integration"
    },
    {
      "check": "PATCH an active link with malformed JSON or a malformed expiresAt value; assert HTTP 400 and verify the persisted expiry is unchanged.",
      "covers": "FR1",
      "id": "TC-FR1-04",
      "level": "integration"
    },
    {
      "check": "PATCH an active link without X-Management-Token; assert the established HTTP 401 missing_token response and verify the expiry is unchanged.",
      "covers": "FR2",
      "id": "TC-FR2-01",
      "level": "integration"
    },
    {
      "check": "PATCH an active link with an incorrect management token; assert the established HTTP 403 invalid_token response and verify the expiry is unchanged.",
      "covers": "FR2",
      "id": "TC-FR2-02",
      "level": "integration"
    },
    {
      "check": "Send wrong-token PATCH requests until the shared management-token failure limit is exceeded; assert the limit produces HTTP 429 rate_limited and that PATCH failures count toward the same limit as the existing management operations.",
      "covers": "FR2",
      "id": "TC-FR2-03",
      "level": "integration"
    },
    {
      "check": "Set a future expiry and verify metadata reflects it and a redirect returns HTTP 410 after the controlled clock passes that expiry; then clear a still-active link's expiry and verify a redirect succeeds after the link's former expiry time.",
      "covers": "FR3",
      "id": "TC-FR3-01",
      "level": "integration"
    },
    {
      "check": "Run expiry update concurrently with click recording through the redirect path; assert the update's expiry is persisted, the redirect remains served, and click recording preserves its expected count and link-state invariants.",
      "covers": "FR3",
      "id": "TC-FR3-02",
      "level": "integration"
    },
    {
      "check": "Race an expiry update against deletion; assert serialization leaves the link deleted, does not resurrect it, and produces either a completed update followed by deletion or a not-found update after deletion.",
      "covers": "FR3",
      "id": "TC-FR3-03",
      "level": "integration"
    },
    {
      "check": "For an already expired link, attempt both setting a future expiry and clearing the expiry; assert each request returns HTTP 410 expired, persisted expiry remains unchanged, and redirects remain expired.",
      "covers": "FR4",
      "id": "TC-FR4-01",
      "level": "integration"
    },
    {
      "check": "On a link that has not expired, submit an expiry equal to the controlled current time and one before it; assert each returns HTTP 400 invalid_expiry and leaves the persisted expiry unchanged.",
      "covers": "FR5",
      "id": "TC-FR5-01",
      "level": "integration"
    },
    {
      "check": "PATCH a deleted link and an unknown link with a valid token; assert HTTP 404 not_found for each and verify the deleted link remains a tombstone.",
      "covers": "FR6",
      "id": "TC-FR6-01",
      "level": "integration"
    },
    {
      "check": "Set a valid expiry far beyond commonly expected near-term dates; assert HTTP 200 and that the returned and persisted expiry equal the requested value, with no update-only maximum applied.",
      "covers": "FR7",
      "id": "TC-FR7-01",
      "level": "integration"
    },
    {
      "check": "Run the existing create, metadata, stats, delete, redirect, health, error-contract, and click-failure-isolation tests; assert their established response contracts, state changes, and redirect behavior remain unchanged.",
      "covers": "NFR1",
      "id": "TC-NFR1-01",
      "level": "integration"
    },
    {
      "check": "Run the existing RedirectLatencyTest with the new endpoint tests; assert it continues to meet its established latency expectation and that redirect resolution does not acquire a new lock or perform additional expiry-update work.",
      "covers": "NFR1",
      "id": "TC-NFR1-02",
      "level": "integration"
    },
    {
      "check": "Parse url-shortener/openapi.yaml as OpenAPI 3.x and assert it defines PATCH /api/links/{code}, the management-token header, required expiresAt with nullable support, the success metadata response, and the documented relevant error responses.",
      "covers": "NFR2",
      "id": "TC-NFR2-01",
      "level": "unit"
    },
    {
      "check": "Check url-shortener/README.md and url-shortener/docs/api.md for the expiry-change operation, authentication, future timestamp and explicit-null request values, omission behavior, and relevant success and error behavior.",
      "covers": "NFR2",
      "id": "TC-NFR2-02",
      "level": "unit"
    },
    {
      "check": "Verify url-shortener/CHANGELOG.md contains an entry for this change and url-shortener/docs/releases/1.0.0-SNAPSHOT.md records the release-readiness review as complete, with verification, compatibility, and documentation readiness addressed.",
      "covers": "NFR3",
      "id": "TC-NFR3-01",
      "level": "unit"
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
import com.example.shortener.api.LinkDtos.UpdateExpiryRequest;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.ManagementTokenRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.CreatedLink;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.util.function.Supplier;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
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
    private final ObjectMapper json;

    public LinkController(LinkService links, CreateRateLimiter rateLimiter, ManagementTokenRateLimiter tokenLimiter,
                          ObjectMapper json) {
        this.links = links;
        this.rateLimiter = rateLimiter;
        this.tokenLimiter = tokenLimiter;
        this.json = json;
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

    /** Sets or removes the expiry (FR1): the same token rules and wrong-token throttle as stats and delete. */
    @PatchMapping("/{code}")
    public LinkMetadata updateExpiry(@PathVariable String code, @RequestBody JsonNode body,
                                     @RequestHeader(name = TOKEN_HEADER, required = false) String token,
                                     HttpServletRequest http) {
        UpdateExpiryRequest request = UpdateExpiryRequest.from(body, json);
        return LinkMetadata.of(withTokenThrottle(http, () -> links.updateExpiry(code, token, request.expiresAt())));
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
import com.example.shortener.service.ApiException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.service.LinkService.LinkStats;

/** Request and response bodies of the /api/links resource. */
public final class LinkDtos {

    private LinkDtos() {
    }

    /** {@code alias} and {@code expiresAt} (ISO-8601 instant) are optional. */
    public record CreateLinkRequest(String url, String alias, Instant expiresAt) {
    }

    /**
     * PATCH body. {@code expiresAt} must be present: an instant sets the expiry, an explicit null
     * removes it. A missing field is rejected rather than read as "remove", so an incomplete request
     * can never clear an expiry by accident.
     */
    public record UpdateExpiryRequest(Instant expiresAt) {

        static UpdateExpiryRequest from(JsonNode body, ObjectMapper json) {
            if (body == null || !body.isObject()) {
                throw ApiException.badRequest("invalid_request", "request body must be a JSON object");
            }
            JsonNode value = body.get("expiresAt");
            if (value == null) {
                throw ApiException.badRequest("invalid_request", "expiresAt is required; use null to remove the expiry");
            }
            if (value.isNull()) {
                return new UpdateExpiryRequest(null);
            }
            try {
                // the application's mapper, so an instant parses exactly as it does at creation
                return new UpdateExpiryRequest(json.convertValue(value, Instant.class));
            } catch (IllegalArgumentException e) {
                throw ApiException.badRequest("invalid_request", "request body is not valid JSON for this endpoint");
            }
        }
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

    /** A new expiry, or null for none; the caller has checked the link is live and the value is valid. */
    public void changeExpiry(Instant expiresAt) {
        this.expiresAt = expiresAt;
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
     * Click recording, deletion and expiry changes all take it, so a click can never be committed
     * after the deletion that erased the link's clicks, and an expiry change never races a deletion.
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
 * deletion and expiry changes take, so a click is never committed after its link's clicks were
 * erased (FR3).
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

/** Link lifecycle: create, resolve for redirect, read metadata and stats, change expiry, delete into a tombstone. */
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
        Instant expiry = futureExpiry(expiresAt, now);

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
     * Sets a new expiry, or removes it when {@code expiresAt} is null. Under the link's row lock, like
     * deletion and click recording. Checks in order: 404 unknown or deleted, the token (401/403), 410
     * if already expired (an expired link is never revived), then the new value must be in the future
     * (400 invalid_expiry), as at creation; there is no maximum. Nothing changes unless all pass.
     */
    @Transactional
    public Link updateExpiry(String code, String managementToken, Instant expiresAt) {
        Link link = repository.lockByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
        authorize(link, managementToken);
        Instant now = now();
        if (link.isExpiredAt(now)) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        link.changeExpiry(futureExpiry(expiresAt, now));
        return repository.saveAndFlush(link);
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

    /** Null stays null (no expiry); otherwise stored precision, and strictly after {@code now}. */
    private static Instant futureExpiry(Instant expiresAt, Instant now) {
        Instant expiry = expiresAt == null ? null : expiresAt.truncatedTo(ChronoUnit.MICROS);
        if (expiry != null && !expiry.isAfter(now)) {
            throw ApiException.badRequest("invalid_expiry", "expiresAt must be in the future");
        }
        return expiry;
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
 * 60-second window, shared by the stats, delete and expiry-change endpoints. Only supplied-but-wrong tokens count;
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

<file path="url-shortener/src/test/java/com/example/shortener/ManagementServerTest.java">
package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assumptions.assumeThat;

import java.io.IOException;
import java.net.ConnectException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Collections;
import java.util.Optional;

import com.example.shortener.support.SecurityHeaders;
import com.example.shortener.support.TestSupportConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;

/**
 * Real listeners on real ports: FR15 (loopback-only management server exposing only health and
 * metrics), FR13 on the management server, and FR17/NFR3 (no visitor data in logs).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.datasource.url=jdbc:h2:mem:mgmt-${random.uuid};DB_CLOSE_DELAY=-1",
        "management.server.port=0"
})
@Import(TestSupportConfig.class)
@ExtendWith(OutputCaptureExtension.class)
class ManagementServerTest {

    private final HttpClient http = HttpClient.newHttpClient();

    @LocalServerPort
    private int port;

    @LocalManagementPort
    private int managementPort;

    @Value("${management.server.address}")
    private String managementAddress;

    @Test
    void TC_FR15_01_onlyHealthAndMetricsOnTheLoopbackManagementPort() throws Exception {
        assertThat(managementAddress).isEqualTo("127.0.0.1");
        assertThat(managementPort).isNotEqualTo(port);
        assertThat(call("127.0.0.1", managementPort, "/actuator/health").statusCode()).isEqualTo(200);
        assertThat(call("127.0.0.1", managementPort, "/actuator/metrics").statusCode()).isEqualTo(200);
        for (String hidden : new String[] {"/actuator/env", "/actuator/beans", "/actuator/configprops", "/actuator/heapdump"}) {
            assertThat(call("127.0.0.1", managementPort, hidden).statusCode()).as(hidden).isEqualTo(404);
        }
        assertThat(call("127.0.0.1", port, "/actuator/health").statusCode()).as("not on the public port").isEqualTo(404);
    }

    @Test
    void TC_FR15_01_managementPortIsUnreachableFromANonLoopbackAddress() {
        Optional<InetAddress> external = nonLoopbackIPv4();
        assumeThat(external).as("this machine has a non-loopback IPv4 address").isPresent();
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(external.get(), managementPort), 2_000);
            throw new AssertionError("management port accepted a connection on " + external.get());
        } catch (ConnectException expected) {
            // refused: nothing listens there
        } catch (IOException other) {
            // also unreachable (e.g. timeout)
        }
    }

    @Test
    void TC_FR13_01_managementResponsesCarryTheSecurityHeadersToo() throws Exception {
        HttpResponse<String> health = call("127.0.0.1", managementPort, "/actuator/health");
        SecurityHeaders.EXPECTED.forEach((name, value) ->
                assertThat(health.headers().firstValue(name)).as(name).hasValue(value));
    }

    @Test
    void TC_FR17_01_noVisitorDataReachesTheLogs(CapturedOutput output) throws Exception {
        for (String path : new String[] {"/Zz9Zz9Zz", "/no/such/route", "/api/links/Zz9Zz9Zz/stats"}) {
            http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                    .header("User-Agent", "LogProbe-Agent/1.0").header("X-Forwarded-For", "203.0.113.177")
                    .header("X-Management-Token", "probe-token-value").header("Cookie", "probe=cookie-value").build(),
                    HttpResponse.BodyHandlers.discarding());
        }
        for (String probe : new String[] {"LogProbe-Agent", "203.0.113.177", "probe-token-value", "cookie-value", "Zz9Zz9Zz"}) {
            assertThat(output.getAll()).as(probe).doesNotContain(probe);
        }
    }

    private HttpResponse<String> call(String host, int targetPort, String path) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create("http://" + host + ":" + targetPort + path)).build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private static Optional<InetAddress> nonLoopbackIPv4() {
        try {
            return Collections.list(NetworkInterface.getNetworkInterfaces()).stream()
                    .flatMap(nic -> Collections.list(nic.getInetAddresses()).stream())
                    .filter(a -> a instanceof Inet4Address && !a.isLoopbackAddress() && !a.isLinkLocalAddress())
                    .findFirst();
        } catch (IOException e) {
            return Optional.empty();
        }
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

<file path="url-shortener/src/test/java/com/example/shortener/api/BodyLimitTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.config.ApiBodyLimitFilter;
import com.example.shortener.support.IntegrationTest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/** FR12: at most 16,384 bytes of request body on /api/**, measured on the bytes actually received. */
class BodyLimitTest extends IntegrationTest {

    @Test
    void TC_FR12_01_bodyOfExactly16384BytesIsAcceptedAnd16385IsRejected() throws Exception {
        mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON).content(jsonOfSize(16_384)))
                .andExpect(status().isCreated());
        mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON).content(jsonOfSize(16_385)))
                .andExpect(status().isPayloadTooLarge());
    }

    /** A request that does not declare its length (chunked): the filter must count what it reads. */
    @Test
    void TC_FR12_01_undeclaredLengthIsMeasuredOnBytesReceived() throws Exception {
        ApiBodyLimitFilter filter = new ApiBodyLimitFilter(16_384, new ObjectMapper());
        AtomicReference<byte[]> forwarded = new AtomicReference<>();

        MockHttpServletResponse rejected = run(filter, jsonOfSize(16_385), forwarded);
        assertThat(rejected.getStatus()).isEqualTo(413);
        assertThat(rejected.getContentAsString()).contains("\"error\":\"payload_too_large\"");
        assertThat(forwarded.get()).as("an oversized body never reaches the application").isNull();

        byte[] ok = jsonOfSize(16_384);
        MockHttpServletResponse accepted = run(filter, ok, forwarded);
        assertThat(accepted.getStatus()).isEqualTo(200);
        assertThat(forwarded.get()).as("a body within the limit is passed on unchanged").isEqualTo(ok);
    }

    @Test
    void TC_FR12_01_onlyApiPathsAreLimited() throws Exception {
        ApiBodyLimitFilter filter = new ApiBodyLimitFilter(10, new ObjectMapper());
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/health");
        request.setContent(new byte[100]);
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> ((MockHttpServletResponse) res).setStatus(200));
        assertThat(response.getStatus()).isEqualTo(200);
    }

    private static MockHttpServletResponse run(ApiBodyLimitFilter filter, byte[] body, AtomicReference<byte[]> seen)
            throws Exception {
        seen.set(null);
        MockHttpServletRequest raw = new MockHttpServletRequest("POST", "/api/links");
        raw.setContent(body);
        var undeclared = new HttpServletRequestWrapper(raw) {
            @Override
            public long getContentLengthLong() {
                return -1; // as with Transfer-Encoding: chunked
            }

            @Override
            public int getContentLength() {
                return -1;
            }
        };
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(undeclared, response, (req, res) -> {
            seen.set(req.getInputStream().readAllBytes());
            ((MockHttpServletResponse) res).setStatus(200);
        });
        return response;
    }

    /** A valid create request padded with JSON whitespace to exactly {@code size} bytes. */
    private static byte[] jsonOfSize(int size) {
        String core = "{\"url\":\"https://example.com/body-limit\"}";
        return (core + " ".repeat(size - core.length())).getBytes(StandardCharsets.UTF_8);
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

<file path="url-shortener/src/test/java/com/example/shortener/api/ErrorContractAndHeadersTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.SecurityHeaders;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;

/** FR4, FR7, FR8, FR13: the error contract (existing codes kept, new ones standard) and security headers. */
class ErrorContractAndHeadersTest extends IntegrationTest {

    @Test
    void TC_FR4_01_existingTokenContractIsUnchangedBelowTheLimit() throws Exception {
        JsonNode link = create("https://example.com/fr4");
        String code = link.get("code").asText();
        for (String path : new String[] {"/api/links/" + code + "/stats", "/api/links/" + code}) {
            boolean isDelete = !path.endsWith("/stats");
            mvc.perform(isDelete ? delete(path) : get(path))
                    .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("missing_token"));
            mvc.perform((isDelete ? delete(path) : get(path)).header("X-Management-Token", "wrong")
                    .with(peer("198.51.100.40")))
                    .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("invalid_token"));
        }
    }

    @Test
    void TC_FR8_01_frameworkErrorsUseTheStandardBody() throws Exception {
        assertStandardError(mvc.perform(get("/no/such/route")).andExpect(status().isNotFound()), "not_found");
        assertStandardError(mvc.perform(put("/api/links")).andExpect(status().isMethodNotAllowed())
                .andExpect(header().string("Allow", "POST")), "method_not_allowed");
        assertStandardError(mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"https://example.com/" + "a".repeat(17_000) + "\"}"))
                .andExpect(status().isPayloadTooLarge()), "payload_too_large");
        assertStandardError(mvc.perform(post("/api/links").contentType(MediaType.TEXT_PLAIN).content("x"))
                .andExpect(status().isUnsupportedMediaType()), "unsupported_media_type");
    }

    @Test
    void TC_FR8_01_existingApplicationErrorCodesAreUnchanged() throws Exception {
        assertStandardError(postLink(Map.of("url", "ftp://example.com")).andExpect(status().isBadRequest()), "invalid_url");
        String alias = uniqueAlias("dup");
        create("https://example.com/dup", alias, null);
        assertStandardError(postLink(Map.of("url", "https://example.com/dup2", "alias", alias))
                .andExpect(status().isConflict()), "alias_taken");
        assertStandardError(mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()), "not_found");
        JsonNode expiring = create("https://example.com/exp", null, "2030-01-01T00:00:01Z");
        clock.advance(java.time.Duration.ofSeconds(5));
        assertStandardError(mvc.perform(get("/" + expiring.get("code").asText())).andExpect(status().isGone()), "expired");
    }

    @Test
    void TC_FR13_01_everyResponseCarriesTheSecurityHeaders() throws Exception {
        JsonNode link = create("https://example.com/headers");
        String code = link.get("code").asText();
        assertSecurityHeaders(mvc.perform(get("/" + code)).andExpect(status().isFound()));             // redirect
        assertSecurityHeaders(mvc.perform(get("/api/links/" + code)).andExpect(status().isOk()));      // success
        assertSecurityHeaders(mvc.perform(get("/health")).andExpect(status().isOk()));                 // public health
        assertSecurityHeaders(mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()));        // app error
        assertSecurityHeaders(mvc.perform(get("/no/such/route")).andExpect(status().isNotFound()));   // framework error
        assertSecurityHeaders(mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content("x".repeat(17_000))).andExpect(status().isPayloadTooLarge()));                // rejected by a filter
    }

    @Test
    void TC_FR16_01_publicHealthIsUnchanged() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("UP"))
                .andExpect(result -> assertThat(json.readTree(result.getResponse().getContentAsString()).size()).isEqualTo(1));
    }

    /** FR7: an unexpected exception becomes a fixed 500 with nothing from the exception in the response. */
    @Nested
    class WhenSomethingUnexpectedBreaks extends IntegrationTest {

        @MockitoBean
        private LinkService links;

        @Test
        void TC_FR7_01_unexpectedErrorIsA500WithNoInternals() throws Exception {
            when(links.metadata(anyString())).thenThrow(
                    new IllegalStateException("SECRET-DETAIL at com.example.Internal.method(Internal.java:42)"));
            MvcResult result = mvc.perform(get("/api/links/abc12345")).andExpect(status().isInternalServerError())
                    .andExpect(jsonPath("$.error").value("internal_error")).andReturn();
            String body = result.getResponse().getContentAsString();
            assertThat(body).doesNotContain("SECRET-DETAIL").doesNotContain("Internal.java").doesNotContain("Exception");
            assertSecurityHeaders(result);
        }
    }

    static void assertStandardError(ResultActions actions, String code) throws Exception {
        MvcResult result = actions.andReturn();
        JsonNode body = new com.fasterxml.jackson.databind.ObjectMapper().readTree(result.getResponse().getContentAsString());
        Set<String> fields = new HashSet<>();
        body.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("error", "message");
        assertThat(body.get("error").asText()).isEqualTo(code);
        assertThat(result.getResponse().getContentType()).startsWith("application/json");
    }

    static void assertSecurityHeaders(ResultActions actions) throws Exception {
        assertSecurityHeaders(actions.andReturn());
    }

    static void assertSecurityHeaders(MvcResult result) {
        SecurityHeaders.EXPECTED.forEach((name, value) -> assertThat(result.getResponse().getHeader(name)).as(name).isEqualTo(value));
    }

    static org.springframework.test.web.servlet.request.RequestPostProcessor peer(String ip) {
        return request -> {
            request.setRemoteAddr(ip);
            return request;
        };
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

<file path="url-shortener/src/test/java/com/example/shortener/api/ManagementTokenRateLimitTest.java">
package com.example.shortener.api;

import static com.example.shortener.api.ErrorContractAndHeadersTest.peer;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.config.ShortenerProperties;
import com.example.shortener.service.ManagementTokenRateLimiter;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;

/** FR10: at most 10 wrong management tokens per client IP per rolling minute, shared by stats and delete. */
class ManagementTokenRateLimitTest extends IntegrationTest {

    private static final AtomicInteger NEXT = new AtomicInteger(1);

    // --- unit: the rolling window --------------------------------------------------------------

    @Test
    void TC_FR10_01_tenWrongTokensAreAdmittedTheEleventhIsLimitedUntilTheWindowRolls() {
        MutableClock time = new MutableClock();
        ManagementTokenRateLimiter limiter = new ManagementTokenRateLimiter(
                new ShortenerProperties("./data", new ShortenerProperties.RateLimit(20, 10), 8, 16_384), time);
        for (int i = 0; i < 10; i++) {
            time.advance(Duration.ofSeconds(1));
            limiter.recordFailure("192.0.2.1"); // attempts at t = 1 .. 10 s
        }
        assertThatThrownBy(() -> limiter.recordFailure("192.0.2.1"))
                .isInstanceOfSatisfying(RateLimitedException.class, e -> {
                    assertThat(e.getError()).isEqualTo("rate_limited");
                    assertThat(e.getRetryAfterSeconds()).isEqualTo(51L); // until the t=1s attempt leaves the window
                });
        assertThatCode(() -> limiter.recordFailure("192.0.2.2")).as("another peer is unaffected").doesNotThrowAnyException();

        time.advance(Duration.ofSeconds(61)); // every attempt (including the rejected ones) has left the window
        assertThatCode(() -> limiter.recordFailure("192.0.2.1")).doesNotThrowAnyException();
    }

    // --- integration: through stats and delete --------------------------------------------------

    @Test
    void TC_FR10_02_wrongTokensAcrossStatsAndDeleteShareOneLimit() throws Exception {
        JsonNode link = create("https://example.com/limit");
        String code = link.get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 10; i++) {
            var request = i % 2 == 0 ? get("/api/links/" + code + "/stats") : delete("/api/links/" + code);
            mvc.perform(request.header("X-Management-Token", "wrong").with(peer(ip)))
                    .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("invalid_token"));
        }
        mvc.perform(delete("/api/links/" + code).header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error").value("rate_limited"))
                .andExpect(header().exists("Retry-After"));
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests());
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isFalse();
    }

    @Test
    void TC_FR10_02_missingTokensNeverCount() throws Exception {
        String code = create("https://example.com/missing").get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 25; i++) {
            mvc.perform(get("/api/links/" + code + "/stats").with(peer(ip)))
                    .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("missing_token"));
        }
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isForbidden());
    }

    @Test
    void TC_FR10_02_validTokenStillWorksWhileTheIpIsLimitedAndForwardedForIsIgnored() throws Exception {
        JsonNode link = create("https://example.com/owner");
        String code = link.get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 11; i++) {
            mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)));
        }
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip))
                        .header("X-Forwarded-For", "203.0.113.200"))
                .andExpect(status().isTooManyRequests()); // a spoofed header does not escape the limit
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", link.get("managementToken").asText())
                        .with(peer(ip)))
                .andExpect(status().isOk()); // the real owner is never locked out
    }

    private static String freshIp() {
        return "198.18.200." + NEXT.getAndIncrement();
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

<file path="url-shortener/src/test/java/com/example/shortener/api/RedirectOutageAndMetricsTest.java">
package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.Collection;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.ServiceUnavailableException;
import com.example.shortener.support.IntegrationTest;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

/** FR6 (database outage on redirect), FR11 and FR14 (redirect outcome metrics, no probing limit). */
class RedirectOutageAndMetricsTest extends IntegrationTest {

    @Autowired
    private MeterRegistry registry;

    @Test
    void TC_FR14_01_eachRedirectOutcomeIsCountedAndTimedWithOnlyAnOutcomeTag() throws Exception {
        JsonNode active = create("https://example.com/m-active");
        JsonNode doomed = create("https://example.com/m-deleted");
        JsonNode expiring = create("https://example.com/m-expired", null, "2030-01-01T00:00:01Z");
        long ok = count("302"), notFound = count("404"), gone = count("410");

        mvc.perform(get("/" + active.get("code").asText())).andExpect(status().isFound());
        mvc.perform(get("/" + active.get("code").asText())).andExpect(status().isFound());
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound());
        mvc.perform(delete("/api/links/" + doomed.get("code").asText())
                .header("X-Management-Token", doomed.get("managementToken").asText())).andExpect(status().isNoContent());
        mvc.perform(get("/" + doomed.get("code").asText())).andExpect(status().isNotFound());
        clock.advance(Duration.ofSeconds(5));
        mvc.perform(get("/" + expiring.get("code").asText())).andExpect(status().isGone());

        assertThat(count("302") - ok).isEqualTo(2);
        assertThat(count("404") - notFound).as("unknown and deleted share one aggregate outcome").isEqualTo(2);
        assertThat(count("410") - gone).isEqualTo(1);
        Timer timer = registry.get(RedirectMetricsInterceptor.METRIC).tag("outcome", "302").timer();
        assertThat(timer.totalTime(java.util.concurrent.TimeUnit.NANOSECONDS)).isPositive();
        assertThat(timer.getId().getTags()).extracting(t -> t.getKey()).containsExactly("outcome");
    }

    @Test
    void TC_FR11_01_repeatedUnknownCodesAreNotRateLimited() throws Exception {
        long before = count("404");
        for (int i = 0; i < 60; i++) {
            mvc.perform(get("/Probe" + String.format("%03d", i))).andExpect(status().isNotFound());
        }
        assertThat(count("404") - before).isEqualTo(60);
    }

    @Test
    void TC_FR14_01_nonRedirectRequestsAreNotCounted() throws Exception {
        long all = allCounts();
        mvc.perform(get("/health"));
        mvc.perform(get("/api/links/Zz9Zz9Zz"));
        mvc.perform(get("/no/such/route"));
        assertThat(allCounts()).isEqualTo(all);
    }

    @Test
    void TC_FR14_01_outcomeMapping() {
        assertThat(RedirectMetricsInterceptor.outcome(302)).isEqualTo("302");
        assertThat(RedirectMetricsInterceptor.outcome(503)).isEqualTo("5xx");
        assertThat(RedirectMetricsInterceptor.outcome(500)).isEqualTo("5xx");
        assertThat(RedirectMetricsInterceptor.outcome(429)).isEqualTo("other");
    }

    /** TC-FR6-01 at the controller: each kind of "the link store cannot answer" becomes the 503. */
    @ParameterizedTest
    @ValueSource(strings = {"resource", "transient", "transaction"})
    void TC_FR6_01_storeFailuresDuringTheLookupBecome503(String kind) {
        LinkService links = mock(LinkService.class);
        RuntimeException failure = switch (kind) {
            case "resource" -> new DataAccessResourceFailureException("db down");
            case "transient" -> new QueryTimeoutException("db slow");
            default -> new CannotCreateTransactionException("no connection");
        };
        when(links.resolve("abc12345")).thenThrow(failure);
        org.assertj.core.api.Assertions.assertThatThrownBy(
                () -> new RedirectController(links, mock(ClickRecorder.class)).redirect("abc12345"))
                .isInstanceOfSatisfying(ServiceUnavailableException.class, e -> {
                    assertThat(e.getError()).isEqualTo("service_unavailable");
                    assertThat(e.getRetryAfterSeconds()).isEqualTo(5L);
                });
    }

    /** TC-FR6-01 through HTTP, and its 5xx metric outcome. */
    @Nested
    class WhenTheLinkStoreIsDown extends IntegrationTest {

        @MockitoBean
        private LinkService links;

        @Autowired
        private MeterRegistry registry;

        @Test
        void TC_FR6_01_redirectReturns503WithRetryAfterFiveAndIsCountedAs5xx() throws Exception {
            when(links.resolve(anyString())).thenThrow(new CannotCreateTransactionException("connection refused"));
            long before = countIn(registry, "5xx");
            mvc.perform(get("/abc12345"))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(header().string("Retry-After", "5"))
                    .andExpect(header().doesNotExist("Location"))
                    .andExpect(jsonPath("$.error").value("service_unavailable"))
                    .andExpect(result -> assertThat(result.getResponse().getContentAsString()).doesNotContain("connection refused"));
            assertThat(countIn(registry, "5xx") - before).isEqualTo(1);
        }
    }

    private long count(String outcome) {
        return countIn(registry, outcome);
    }

    private long allCounts() {
        Collection<Timer> timers = registry.find(RedirectMetricsInterceptor.METRIC).timers();
        return timers.stream().mapToLong(Timer::count).sum();
    }

    static long countIn(MeterRegistry registry, String outcome) {
        Timer timer = registry.find(RedirectMetricsInterceptor.METRIC).tag("outcome", outcome).timer();
        return timer == null ? 0 : timer.count();
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

<file path="url-shortener/src/test/java/com/example/shortener/support/SecurityHeaders.java">
package com.example.shortener.support;

import java.util.Map;

/** The browser-hardening headers every response must carry (FR13). */
public final class SecurityHeaders {

    public static final Map<String, String> EXPECTED = Map.of(
            "X-Content-Type-Options", "nosniff",
            "X-Frame-Options", "DENY",
            "Referrer-Policy", "no-referrer",
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");

    private SecurityHeaders() {
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

<file path="url-shortener/src/test/resources/application.properties">
# Tests start real servers (restart, upgrade and listener tests): an ephemeral management port
# avoids clashing with anything on the fixed production port 8081. Applies to every test.
management.server.port=0
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
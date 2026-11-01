# Test plan

_30 cases cover all 19 functional requirements and all 4 non-functional requirements, including specified failure paths, abuse limits, response contracts, observability, and release gates._

| Id | Covers | Level | Check |
|---|---|---|---|
| TC-FR1-01 | FR1 | integration | Request a pre-existing active link and verify the response is the existing 302 with the same Location and Cache-Control behavior; verify the stored destination is unchanged. |
| TC-FR2-01 | FR2 | integration | Verify existing expired and deleted link records retain their current 410 and 404 behavior across an application restart, and verify no migration changes the existing link or tombstone data. |
| TC-FR3-01 | FR3 | integration | Submit invalid create input and a conflicting alias; verify each returns its existing 400 or 409 status and exact existing error code. |
| TC-FR4-01 | FR4 | integration | Call stats and delete without a token and with an incorrect token below the limit; verify respectively 401/missing_token and 403/invalid_token. |
| TC-FR5-01 | FR5 | integration | Request unknown and deleted codes and an expired link; verify 404/not_found for the first two and 410/expired for the last. |
| TC-FR6-01 | FR6 | integration | Make the database link lookup fail during a redirect; verify 503/service_unavailable, Retry-After: 5, the standard JSON error body, and exactly one lookup attempt. |
| TC-FR7-01 | FR7 | integration | Cause an unexpected server exception; verify 500/internal_error with the standard JSON body and confirm the response contains no exception text, stack trace, or internal details. |
| TC-FR8-01 | FR8 | integration | Exercise application and framework errors, including unmatched route, unsupported method, oversized body, and unexpected exception; verify each has application/json and exactly the error and message fields with its specified status/code pair. |
| TC-FR9-01 | FR9 | integration | From one direct peer IP, create 20 links within a minute and verify they are admitted; verify the next create returns 429/rate_limited with a Retry-After header. |
| TC-FR10-01 | FR10 | unit | With a controlled clock, verify the limiter admits 10 supplied incorrect attempts per peer in a rolling 60-second window, blocks the next incorrect attempt with a positive delta-seconds retry time, and admits an attempt after the oldest blocking entry expires. |
| TC-FR10-02 | FR10 | integration | Make 10 incorrect-token requests distributed across stats and delete from one direct peer; verify the next incorrect request to either route returns 429/rate_limited with Retry-After. Verify missing-token requests return 401 without consuming attempts, a valid token is still processed at the limit, and spoofed forwarding headers do not change the peer identity. |
| TC-FR11-01 | FR11 | integration | Issue a sequence of unknown and deleted-code redirects from one peer; verify none is rate-limited and their metrics share one aggregate 404 outcome with no code or cause dimension. |
| TC-FR12-01 | FR12 | integration | Send /api/** bodies of exactly 16,384 and 16,385 actual bytes; verify the boundary-sized request is not rejected for size and the larger request returns 413/payload_too_large with the standard JSON body. Repeat with absent or inaccurate Content-Length to verify enforcement uses received bytes. |
| TC-FR13-01 | FR13 | integration | Inspect representative success, redirect, error, public health, and Actuator responses; verify all include X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: no-referrer, and Content-Security-Policy: default-src 'none'; frame-ancestors 'none'. |
| TC-FR14-01 | FR14 | integration | Generate redirect outcomes 302, 404, 410, and 5xx, then query local Actuator metrics; verify each outcome count and redirect timing are observable, and unknown/deleted 404s are aggregated without code- or cause-specific labels. |
| TC-FR15-01 | FR15 | integration | Verify the management listener is bound to 127.0.0.1 on its separate port, health and metrics are reachable locally, no other Actuator endpoint is exposed, and a request through the public listener cannot reach Actuator. |
| TC-FR16-01 | FR16 | integration | Request /health on the main port and verify its existing status and response body are unchanged. |
| TC-FR17-01 | FR17 | integration | Exercise successful and failed visitor redirects, then inspect captured application logs; verify the change emits no visitor-specific code, IP, destination, or request logging. |
| TC-FR18-01 | FR18 | integration | Redirect to a destination served by a recording test server and verify no outbound request is made; verify redirect handling performs no destination retry or reputation/malware lookup and introduces no authentication requirement beyond the existing management token. |
| TC-FR19-01 | FR19 | unit | Review the change manifest and build artifacts; verify changes are confined to the url-shortener service and introduce no infrastructure, deployment, or third-party integration changes. |
| TC-NFR1-01 | NFR1 | integration | With the service and database available, request active links repeatedly and verify every response is the expected successful redirect and none is 5xx. |
| TC-NFR2-01 | NFR2 | integration | Run the existing in-process redirect latency check and verify the measured p99 is below 50 ms. |
| TC-NFR3-01 | NFR3 | integration | Capture logs while exercising visitor requests and verify no new visitor-specific log entries or fields are emitted. |
| TC-NFR4-01 | NFR4 | integration | Run the complete existing and new automated test suite; verify all tests pass, the reported suite count is at least 95, and automated tests exercise the required security headers and error behavior. |

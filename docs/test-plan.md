# Test plan

_32 cases covering all functional requirements (FR1–FR6), all testable non-functional requirements (NFR1–NFR5), and the specified success and failure paths._

| Id | Covers | Level | Check |
|---|---|---|---|
| TC-FR1-01 | FR1 — generated-code creation response | integration | POST a valid HTTP URL without optional fields; assert HTTP 201, an 8-character code matching [A-Za-z0-9_-], a relative shortPath corresponding to the code, and a managementToken in the creation response. |
| TC-FR1-02 | FR1 — custom alias creation | integration | POST a valid URL with a valid custom alias; assert HTTP 201 and that the response code and shortPath use that exact, case-sensitive alias. |
| TC-FR1-03 | FR1 — custom alias validation | integration | For aliases shorter than 3 characters, longer than 32 characters, containing characters outside [A-Za-z0-9_-], or equal to a reserved service path (including api, health, and links), assert HTTP 400 and no link is created. |
| TC-FR1-04 | FR1 — alias conflicts | integration | Create an active link with an alias, then POST another link using that alias; assert HTTP 409. Repeat with an alias reserved by a tombstone and assert HTTP 409. |
| TC-FR1-05 | FR1 — generated-code collision handling | unit | Make the code generator produce a code already assigned to an active link, then a code reserved by a tombstone, followed by an unused code; assert the service retries and returns only the unused code. |
| TC-FR2-01 | FR2 — expiry boundary | integration | Create a link expiring at a controlled future instant; assert redirect succeeds before that instant and returns HTTP 410 at and after it. |
| TC-FR2-02 | FR2 — invalid expiry | integration | POST a link with an expiry at or before its creation time and with a malformed expiry value; assert HTTP 400 and no link is created. |
| TC-FR2-03 | FR2 — expiry does not delete metadata | integration | After a link expires, GET /api/links/{code}; assert HTTP 200 and that its public metadata remains available. |
| TC-FR3-01 | FR3 — active redirect | integration | GET an active, unexpired code; assert HTTP 302, Location exactly equals the original URL, and Cache-Control includes no-store. |
| TC-FR3-02 | FR3 — expired redirect | integration | GET a code whose expiry has passed; assert HTTP 410 and that no redirect Location is returned. |
| TC-FR3-03 | FR3 — unknown and deleted redirects | integration | GET an unknown code and a previously deleted code; assert HTTP 404 for both and no redirect Location. |
| TC-FR4-01 | FR4 — public metadata | integration | GET metadata for an active link without credentials; assert HTTP 200 and the exact originalUrl, a creation timestamp, and expiresAt (null when no expiry was set). |
| TC-FR4-02 | FR4 — metadata for unknown and deleted codes | integration | GET metadata for an unknown code and a deleted code; assert HTTP 404 for both. |
| TC-FR5-01 | FR5 — authorized deletion and tombstone | integration | DELETE an active link with its management token; assert HTTP 204 and an empty response body, then verify the destination is erased, redirects and metadata return 404, and creating the same alias returns 409. |
| TC-FR5-02 | FR5 — missing deletion token | integration | DELETE an active link without X-Management-Token; assert HTTP 401 and verify the link still redirects to its original URL. |
| TC-FR5-03 | FR5 — invalid deletion token | integration | DELETE an active link with an incorrect X-Management-Token; assert HTTP 403 and verify the link is not deleted. |
| TC-FR5-04 | FR5 — deletion of missing or already-deleted code | integration | DELETE an unknown code and a previously deleted code with a token header; assert HTTP 404 for both. |
| TC-FR5-05 | FR5 — token confidentiality and hash-only storage | integration | Create a link and inspect its persisted record and subsequent metadata/redirect responses; assert the plaintext management token is absent outside the create response and only a SHA-256 token hash is persisted. |
| TC-FR6-01 | FR6 — healthy service and persistence store | integration | With the Spring service and H2 store available, GET /health and assert HTTP 200 with status UP. |
| TC-FR6-02 | FR6 — unavailable persistence store | integration | Make the persistence health check fail while the application remains running; GET /health and assert HTTP 503. |
| TC-NFR1-01 | NFR1 — indicative redirect latency | integration | Run 1,000 sequential redirect warm-up requests followed by 1,000 sequential measured requests from one in-process client on the local machine; calculate measured p99 and assert it is below 50 ms. |
| TC-NFR2-01 | NFR2 — URL syntax, scheme, and length | integration | POST malformed URLs, a URL longer than 2,048 characters, and URLs using non-HTTP(S) schemes; assert HTTP 400 for each and verify no link is created. |
| TC-NFR2-02 | NFR2 — prohibited localhost and address literals | unit | Validate localhost and representative loopback, private, link-local, unique-local, and multicast IPv4 and IPv6 literals; assert every prohibited destination is rejected. |
| TC-NFR2-03 | NFR2 — prohibited DNS results | unit | With a deterministic resolver, test a hostname resolving only to prohibited addresses and one resolving to a mix of allowed and prohibited addresses across IPv4 and IPv6; assert both are rejected. |
| TC-NFR2-04 | NFR2 — DNS resolution failure | unit | Make the resolver time out, fail, or return no usable addresses; assert URL validation fails closed. |
| TC-NFR2-05 | NFR2 — valid public destination | unit | With a deterministic resolver returning only permitted addresses, validate syntactically valid HTTP and HTTPS URLs at or below the 2,048-character limit; assert they are accepted. |
| TC-NFR2-06 | NFR2 — destination is never fetched | unit | Create a link using a permitted test hostname and a spy on outbound HTTP clients; assert creation succeeds and no request is made to the destination. |
| TC-NFR3-01 | NFR3 — per-IP creation limit | integration | From one peer IP, send 20 create requests within the configured minute and then a 21st; assert the first 20 are processed and the limited request returns HTTP 429 with a Retry-After header. |
| TC-NFR3-02 | NFR3 — IP isolation and forwarded-header handling | integration | Exhaust the creation bucket for one peer IP, then send a create request from a different peer IP and assert it is not limited; verify changing X-Forwarded-For alone does not change the bucket identity. |
| TC-NFR3-03 | NFR3 — rejected attempts count and restart reset | integration | Use an invalid create request among requests from one IP and verify it consumes a bucket token; after the limit is reached, restart the service and assert that IP can create again. |
| TC-NFR4-01 | NFR4 — persistence and Flyway migrations | integration | Start the service with a temporary ./data H2 store, create a link and a tombstone, restart using the same store, and assert the active link and reserved tombstone remain available and Flyway reports its migrations applied. |
| TC-NFR4-02 | NFR4 — local startup | integration | Run the documented single local startup command in an environment without external infrastructure; assert the service starts, applies migrations to the file-based H2 store under ./data, and responds to an HTTP health request. |
| TC-NFR5-01 | NFR5 — automated functional and failure-path coverage | integration | Run the automated service test suite and assert it includes executable tests for creation, validation, alias conflicts, expiry, redirects, metadata, authorized and rejected deletion, rate limiting, restart persistence, health, and redirect latency. |

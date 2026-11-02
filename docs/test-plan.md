# Test plan

_19 cases covering FR1–FR7 and NFR1–NFR3, including endpoint success and failure paths, shared throttling, concurrency, compatibility, and release artifacts._

| Id | Covers | Level | Check |
|---|---|---|---|
| TC-FR1-01 | FR1 | integration | PATCH an active link with a valid management token and future expiresAt; assert HTTP 200 and that the response metadata contains the requested expiry. |
| TC-FR1-02 | FR1 | integration | PATCH an active link with expiresAt explicitly set to null; assert HTTP 200 and response metadata contains expiresAt: null. |
| TC-FR1-03 | FR1 | integration | PATCH an active link with expiresAt omitted; assert HTTP 400 and verify the persisted expiry is unchanged. |
| TC-FR1-04 | FR1 | integration | PATCH an active link with malformed JSON or a malformed expiresAt value; assert HTTP 400 and verify the persisted expiry is unchanged. |
| TC-FR2-01 | FR2 | integration | PATCH an active link without X-Management-Token; assert the established HTTP 401 missing_token response and verify the expiry is unchanged. |
| TC-FR2-02 | FR2 | integration | PATCH an active link with an incorrect management token; assert the established HTTP 403 invalid_token response and verify the expiry is unchanged. |
| TC-FR2-03 | FR2 | integration | Send wrong-token PATCH requests until the shared management-token failure limit is exceeded; assert the limit produces HTTP 429 rate_limited and that PATCH failures count toward the same limit as the existing management operations. |
| TC-FR3-01 | FR3 | integration | Set a future expiry and verify metadata reflects it and a redirect returns HTTP 410 after the controlled clock passes that expiry; then clear a still-active link's expiry and verify a redirect succeeds after the link's former expiry time. |
| TC-FR3-02 | FR3 | integration | Run expiry update concurrently with click recording through the redirect path; assert the update's expiry is persisted, the redirect remains served, and click recording preserves its expected count and link-state invariants. |
| TC-FR3-03 | FR3 | integration | Race an expiry update against deletion; assert serialization leaves the link deleted, does not resurrect it, and produces either a completed update followed by deletion or a not-found update after deletion. |
| TC-FR4-01 | FR4 | integration | For an already expired link, attempt both setting a future expiry and clearing the expiry; assert each request returns HTTP 410 expired, persisted expiry remains unchanged, and redirects remain expired. |
| TC-FR5-01 | FR5 | integration | On a link that has not expired, submit an expiry equal to the controlled current time and one before it; assert each returns HTTP 400 invalid_expiry and leaves the persisted expiry unchanged. |
| TC-FR6-01 | FR6 | integration | PATCH a deleted link and an unknown link with a valid token; assert HTTP 404 not_found for each and verify the deleted link remains a tombstone. |
| TC-FR7-01 | FR7 | integration | Set a valid expiry far beyond commonly expected near-term dates; assert HTTP 200 and that the returned and persisted expiry equal the requested value, with no update-only maximum applied. |
| TC-NFR1-01 | NFR1 | integration | Run the existing create, metadata, stats, delete, redirect, health, error-contract, and click-failure-isolation tests; assert their established response contracts, state changes, and redirect behavior remain unchanged. |
| TC-NFR1-02 | NFR1 | integration | Run the existing RedirectLatencyTest with the new endpoint tests; assert it continues to meet its established latency expectation and that redirect resolution does not acquire a new lock or perform additional expiry-update work. |
| TC-NFR2-01 | NFR2 | unit | Parse url-shortener/openapi.yaml as OpenAPI 3.x and assert it defines PATCH /api/links/{code}, the management-token header, required expiresAt with nullable support, the success metadata response, and the documented relevant error responses. |
| TC-NFR2-02 | NFR2 | unit | Check url-shortener/README.md and url-shortener/docs/api.md for the expiry-change operation, authentication, future timestamp and explicit-null request values, omission behavior, and relevant success and error behavior. |
| TC-NFR3-01 | NFR3 | unit | Verify url-shortener/CHANGELOG.md contains an entry for this change and url-shortener/docs/releases/1.0.0-SNAPSHOT.md records the release-readiness review as complete, with verification, compatibility, and documentation readiness addressed. |

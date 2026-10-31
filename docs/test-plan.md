# Test plan

_22 cases covering all functional requirements, all testable non-functional requirements, specified API behavior, and identified failure and concurrency paths._

| Id | Covers | Level | Check |
|---|---|---|---|
| TC-FR1-01 | FR1 | integration | Create an active link and GET its redirect route; assert the existing successful 302 response, Location and no-store headers are unchanged, then fetch authorized stats and assert totalClicks increased by exactly one. |
| TC-FR1-02 | FR1 | integration | Request a nonexistent and an expired redirect; assert each retains its existing non-success response and neither request creates a click event. |
| TC-FR1-03 | FR1 | unit | Force the click-event persistence operation to throw while handling a successful redirect; assert the redirect result remains 302 with the original Location and no-store headers. |
| TC-FR2-01 | FR2 | integration | With a fixed UTC clock and click events spanning the 30-day window plus an older event, request authorized stats; assert totalClicks includes all events, dailyClicks has exactly 30 YYYY-MM-DD entries in oldest-first order, every empty day is zero, boundary-day clicks are assigned to the correct UTC dates, and lastClickedAt is the latest event timestamp in ISO-8601 UTC. |
| TC-FR2-02 | FR2 | integration | Request authorized stats for a link with no events; assert totalClicks is 0, dailyClicks contains exactly 30 zero-count entries in oldest-first order, and lastClickedAt is null. |
| TC-FR2-03 | FR2 | integration | Request stats for an existing link without X-Management-Token and with a blank header; assert both requests return 401 using the existing error JSON convention and disclose no stats. |
| TC-FR2-04 | FR2 | integration | Request stats for an existing link with a non-matching management token; assert the response is 403 using the existing error JSON convention and contains no stats. |
| TC-FR2-05 | FR2 | integration | Request stats for an unknown code with a token header; assert the response is 404 and contains no stats. |
| TC-FR3-01 | FR3 | integration | Create an expired but not deleted link with recorded clicks and request stats using its management token; assert stats return 200 with the persisted counts and latest timestamp. |
| TC-FR3-02 | FR3 | integration | Record clicks, delete the link with its management token, and assert the delete response remains 204, the link is a tombstone, no click events remain for its link id, and a subsequent stats request returns 404. |
| TC-FR3-03 | FR3 | integration | Coordinate a redirect click-recording operation with deletion of the same link; after both operations complete, assert the link remains a tombstone and the database contains no click events for it. |
| TC-FR3-04 | FR3 | integration | Request stats for a deleted link with a token header; assert the response is 404 and contains no stats. |
| TC-FR4-01 | FR4 | integration | Run the existing link-creation contract test and assert request validation, status, response fields, and created-link behavior are unchanged. |
| TC-FR4-02 | FR4 | integration | Run the existing public metadata contract test and assert its response status, JSON fields, and behavior are unchanged by click analytics. |
| TC-FR4-03 | FR4 | integration | Run the existing deletion lifecycle contract test and assert its authorization statuses and successful 204 response with no body remain unchanged. |
| TC-FR5-01 | FR5 | integration | Record clicks and fetch stats; assert the JSON contains only totalClicks, dailyClicks, and lastClickedAt as click metrics and has no unique-visitor field or visitor count. |
| TC-NFR1-01 | NFR1 | integration | Run the redirect persistence-failure scenario through the running Spring context; assert the response remains the existing 302 with its Location and no-store headers even when click insertion fails. |
| TC-NFR1-02 | NFR1 | integration | Run the existing RedirectLatencyTest with click recording enabled and assert its p99 redirect latency remains below 50 ms. |
| TC-NFR2-01 | NFR2 | integration | Record clicks while supplying request IP, user-agent, cookie, and other visitor-like headers; inspect the persisted click-event schema and rows and stats JSON, and assert no visitor identifiers, fingerprints, or unique-visitor data are stored or returned. |
| TC-NFR3-01 | NFR3 | integration | Record clicks in the file-backed database, stop and restart the application against the same database, then request authorized stats and assert the lifetime total, daily counts, and latest timestamp still reflect the recorded events. |
| TC-NFR4-01 | NFR4 | integration | Start the Spring application against both a clean database and an existing file-backed database; assert Flyway applies V2 without modifying V1, schema validation succeeds, and the click-event table and indexes are available. |
| TC-NFR5-01 | NFR5 | integration | Run the complete existing and added automated test suite; assert all tests pass, including link creation, lifecycle, stats, restart persistence, and redirect latency tests. |

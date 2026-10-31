# Requirement: Click analytics for the URL shortener (brownfield)

> Input to the orchestrator. The service in `url-shortener/` already exists and
> is in use; this is an enhancement to it, not a rewrite.

## Goal
Link owners want to know how their short links perform. Record visits to short
links and expose simple statistics for each link.

## Functional requirements
- FR1 Every successful redirect counts as a click on that link.
- FR2 A stats endpoint returns, for a link: total clicks, clicks per day for
  the recent past, and when it was last clicked.
- FR3 Stats remain available for expired links; deleted links have no stats.
- FR4 Existing behaviour of create, redirect, metadata and delete must not change.

## Non-functional requirements
- NFR1 The redirect path is latency-sensitive: the existing p99 < 50 ms check must
  keep passing, and recording a click must never make a redirect fail.
- NFR2 Privacy: we must not build profiles of visitors.
- NFR3 Click data must survive restarts, like links do.
- NFR4 Changes follow the existing architecture and conventions of the codebase.
- NFR5 The existing test suite keeps passing; new behaviour is covered by new tests.

## Known open points (for the Analyst to resolve or flag)
- How many days of per-day history to return.
- Whether stats are public like metadata, or need the management token.
- Whether "unique visitors" should be reported.
- What happens to click data when a link is deleted.

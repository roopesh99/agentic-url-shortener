# Requirement: URL Shortener Service (v1, greenfield)

> Input to the orchestrator. Written as a product owner would: intentionally
> mostly-specified, with a few open points the Analyst agent must surface.

## Goal
Provide an HTTP service that turns long URLs into short, shareable links and
redirects visitors from the short link to the original URL.

## Functional requirements
- FR1 Create a short link for a long URL. Optionally accept a custom alias.
- FR2 Optionally accept an expiry; expired links must stop redirecting.
- FR3 Visiting a short link redirects to the original URL.
- FR4 Fetch metadata for a short link (original URL, created, expiry).
- FR5 Delete a short link.
- FR6 Health endpoint for operations.

## Non-functional requirements
- NFR1 Redirect path is latency-sensitive (target p99 < 50 ms in-process).
- NFR2 Only `http`/`https` URLs are accepted; reject obviously malicious or
  internal-network targets.
- NFR3 Protect the create endpoint from abuse.
- NFR4 Runs locally with a single command; no external infrastructure.
- NFR5 Automated tests with meaningful coverage.

## Known open points (for the Analyst to resolve or flag)
- Short-code length / alphabet not specified.
- Redirect status code (301 vs 302) not specified.
- Behaviour when a custom alias is already taken.
- Rate-limit thresholds not specified.

# Requirement: Let link owners change a link's expiry (full lifecycle)

> Input to the orchestrator for the full-lifecycle workflow (design, documentation and release
> readiness included). The service in `url-shortener/` exists and is in use.

## Goal
Owners sometimes set an expiry that turns out to be too short, or forget to set one. Let the owner
of a link change its expiry after creation.

## Functional requirements
- FR1 The owner of a link can set a new expiry, or remove the expiry, for that link.
- FR2 Only the link's owner (holder of its management token) can do this.
- FR3 The change takes effect immediately for redirects and is visible in the link's metadata.

## Non-functional requirements
- NFR1 Existing endpoints and their behaviour do not change.
- NFR2 The service's API is described by a machine-readable definition, and the service is documented
  for operators and API clients.
- NFR3 The release is prepared with a changelog and a readiness review before it ships.

## Known open points (for the Analyst to resolve or flag)
- Whether an already expired link can be brought back to life by extending its expiry.
- Whether there is a maximum expiry.

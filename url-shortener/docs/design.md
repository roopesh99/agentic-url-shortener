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

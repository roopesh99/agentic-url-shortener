# URL Shortener API reference

This reference follows [`../openapi.yaml`](../openapi.yaml), OpenAPI 3.0.3. Paths are relative to the server root (`/`). Unless stated otherwise, errors use JSON with this shape:

```json
{"error":"stable_code","message":"human-readable explanation"}
```

Management tokens are sent in the `X-Management-Token` header. Link creation returns the plaintext token once; retain it securely. The service stores a hash and does not return the token from later operations. Responses include the security headers described in the OpenAPI definition.

## `POST /api/links` — Create a short link

Creates a link and returns its code, short path, and one-time plaintext management token. Creation requests are rate-limited per client peer address.

**Request:** `Content-Type: application/json`; required JSON object with `url` (HTTP or HTTPS destination, up to 2,048 characters). Optional `alias` is a custom 3–32 character code using letters, digits, `_`, or `-`. Optional `expiresAt` is a nullable ISO-8601 date-time instant; if non-null it must be in the future. There is no maximum expiry.

```json
{
  "url": "https://example.com/article",
  "alias": "article",
  "expiresAt": "2030-01-01T00:00:00Z"
}
```

**Responses:**

- `201 Created` — `CreateLinkResponse` JSON: `code`, `shortPath`, and `managementToken`. `Location` identifies the relative metadata URI.
- `400 Bad Request` — `invalid_request`, `invalid_url`, `prohibited_destination`, `invalid_expiry`, `invalid_alias`, or `reserved_alias`, depending on the failure.
- `405 Method Not Allowed` — `method_not_allowed`.
- `409 Conflict` — `alias_taken`.
- `413 Payload Too Large` — `payload_too_large`.
- `415 Unsupported Media Type` — `unsupported_media_type`; send JSON.
- `429 Too Many Requests` — `rate_limited`; includes `Retry-After`.
- `500 Internal Server Error` — `internal_error`.
- `503 Service Unavailable` — `service_unavailable` or `code_collision`.

**Example:**

```sh
curl -i -X POST http://localhost:8080/api/links \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article","expiresAt":"2030-01-01T00:00:00Z"}'
```

Keep the returned management token; it is needed for private statistics, deletion, and expiry updates.

## `GET /api/links/{code}` — Get public link metadata

Returns metadata for a live or expired link. Unknown and deleted links are not exposed. This endpoint does not require a management token.

**Path parameter:** `code` is the link code or custom alias.

**Request:** No body.

**Responses:**

- `200 OK` — `LinkMetadata` JSON: `code`, nullable `alias`, `originalUrl`, `createdAt`, and nullable `expiresAt`. Expired links can still be inspected.
- `404 Not Found` — `not_found` for an unknown or deleted link.
- `405 Method Not Allowed` — `method_not_allowed`.
- `413 Payload Too Large` — `payload_too_large`.
- `500 Internal Server Error` — `internal_error`.

**Example:**

```sh
curl -i http://localhost:8080/api/links/abc12345
```

## `PATCH /api/links/{code}` — Set or remove a link expiry

Changes only the expiry of an existing link. Requires the link's management token in `X-Management-Token`. A successful update is committed before the response, and the returned public metadata contains the new expiry. Subsequent metadata and redirect lookups use the persisted value.

**Path parameter:** `code` is the link code or custom alias.

**Request:** `Content-Type: application/json`; a JSON object with the required `expiresAt` field:

- Supply a future ISO-8601 instant to set the expiry.
- Supply explicit `null` to remove the expiry.
- Omit the field and the request is rejected; omission does not clear or otherwise change the link.
- A value at or before the current time is rejected. No maximum expiry is imposed.

The timestamp is parsed using the same rules as link creation and stored at microsecond precision.

**Responses:**

- `200 OK` — updated `LinkMetadata` JSON; `expiresAt` contains the new instant or `null` if removed.
- `400 Bad Request` — `invalid_expiry` for a non-future instant; `invalid_request` for omission, malformed JSON, or a value that cannot be parsed. No change is made on failure.
- `401 Unauthorized` — `missing_token` when the header is missing or blank. No change is made.
- `403 Forbidden` — `invalid_token` for an incorrect token. No change is made.
- `404 Not Found` — `not_found` for an unknown or deleted link. No change is made.
- `405 Method Not Allowed` — `method_not_allowed`.
- `410 Gone` — `expired` if the link was already expired when the authorized update was processed. An expired link cannot be revived; no change is made.
- `413 Payload Too Large` — `payload_too_large`.
- `415 Unsupported Media Type` — `unsupported_media_type`; send JSON.
- `429 Too Many Requests` — `rate_limited` when the shared wrong-management-token limit is exceeded; includes `Retry-After`.
- `500 Internal Server Error` — `internal_error`.

Missing-token failures return `401`; wrong-token failures return `403` until the shared limit is exceeded. Wrong-token attempts for statistics, deletion, and expiry updates share that limit. Link lookup occurs before token authorization, so unknown or deleted links return `404`.

**Set an expiry:**

```sh
curl -i -X PATCH http://localhost:8080/api/links/abc12345 \
  -H 'X-Management-Token: YOUR_MANAGEMENT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"expiresAt":"2030-01-01T00:00:00Z"}'
```

**Remove an expiry:**

```sh
curl -i -X PATCH http://localhost:8080/api/links/abc12345 \
  -H 'X-Management-Token: YOUR_MANAGEMENT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"expiresAt":null}'
```

## `DELETE /api/links/{code}` — Delete a link

Deletes a link into a tombstone. Expiry does not prevent deletion. A valid management token is required.

**Path parameter:** `code` is the link code or custom alias.

**Request:** No body. Send `X-Management-Token`; although the OpenAPI parameter is optional at the HTTP parameter level, the operation requires a valid token.

**Responses:**

- `204 No Content` — deleted; no response body.
- `401 Unauthorized` — `missing_token`.
- `403 Forbidden` — `invalid_token`.
- `404 Not Found` — `not_found` for an unknown or already deleted link.
- `405 Method Not Allowed` — `method_not_allowed`.
- `413 Payload Too Large` — `payload_too_large`.
- `429 Too Many Requests` — `rate_limited`; includes `Retry-After`.
- `500 Internal Server Error` — `internal_error`.

**Example:**

```sh
curl -i -X DELETE http://localhost:8080/api/links/abc12345 \
  -H 'X-Management-Token: YOUR_MANAGEMENT_TOKEN'
```

## `GET /api/links/{code}/stats` — Get private link statistics

Returns lifetime clicks, daily click counts for the current UTC day and previous 29 days (30 days total, oldest first, including zero-count days), and the last click time. Expired links retain statistics; deleted links do not. Requires the link's management token.

**Path parameter:** `code` is the link code or custom alias.

**Request:** No body. Send `X-Management-Token`.

**Responses:**

- `200 OK` — `StatsResponse` JSON with `totalClicks`, `dailyClicks` (`date` and `clicks` per day), and nullable `lastClickedAt`.
- `401 Unauthorized` — `missing_token`.
- `403 Forbidden` — `invalid_token`.
- `404 Not Found` — `not_found` for an unknown or deleted link.
- `405 Method Not Allowed` — `method_not_allowed`.
- `413 Payload Too Large` — `payload_too_large`.
- `429 Too Many Requests` — `rate_limited`; includes `Retry-After`. Wrong-token attempts share a limit with deletion and expiry updates.
- `500 Internal Server Error` — `internal_error`.

**Example:**

```sh
curl -i http://localhost:8080/api/links/abc12345/stats \
  -H 'X-Management-Token: YOUR_MANAGEMENT_TOKEN'
```

## `GET /{code}` — Redirect to the original URL

Resolves an active short link, records a click best-effort, and returns a non-cacheable redirect. Click-recording failures do not prevent the redirect.

**Path parameter:** `code` matches 3–32 ASCII letters, digits, underscores, or hyphens.

**Request:** No body or token required.

**Responses:**

- `302 Found` — redirects to the destination in `Location`; `Cache-Control: no-store`.
- `404 Not Found` — `not_found` for an unknown or deleted code.
- `405 Method Not Allowed` — `method_not_allowed`.
- `410 Gone` — `expired` for an expired link.
- `500 Internal Server Error` — `internal_error`.
- `503 Service Unavailable` — `service_unavailable` if the link store cannot serve the redirect; includes `Retry-After`.

**Example:**

```sh
curl -i http://localhost:8080/abc12345
```

## `GET /health` — Check public service health

Checks whether the service can reach its database.

**Request:** No body.

**Responses:**

- `200 OK` — JSON `{"status":"UP"}`.
- `405 Method Not Allowed` — `method_not_allowed`.
- `500 Internal Server Error` — `internal_error`.
- `503 Service Unavailable` — JSON `{"status":"DOWN"}` when the database is unavailable.

**Example:**

```sh
curl -i http://localhost:8080/health
```

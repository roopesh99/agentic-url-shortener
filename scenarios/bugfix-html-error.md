# Bug report: some bad requests get an HTML page instead of a JSON error

> Found by the release smoke test, which starts the packaged service and calls it over HTTP.

## What happens
A client that sends a request whose path contains a malformed percent-escape, for example

    GET /api/links/%ZZ

gets `400 Bad Request` with an HTML page ("HTTP Status 400 – Bad Request", Content-Type
`text/html`) from the embedded server. Client libraries that parse every error as JSON fail on it.

## Expected
Every error response from the public API uses the service's documented JSON error body
(`{"error": ..., "message": ...}` with `Content-Type: application/json`), as other bad requests
already do (malformed JSON bodies, unsupported media types, unknown paths, wrong methods). The
status code for this case stays 400.

## Notes
- The in-process test suite does not show the problem: it happens in the real HTTP server, before
  the request reaches the application's controllers.
- Nothing else about request handling, status codes or headers should change.

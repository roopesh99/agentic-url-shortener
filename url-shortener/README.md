# URL Shortener

An HTTP service for creating short links, inspecting link metadata and click statistics, managing links with per-link management tokens, and redirecting short codes to their destinations. Link data is stored in a file-based H2 database and survives restarts. Deleted links remain as tombstones so their codes are not reused.

## Build, run, and test

The supplied source snapshot does not include a build descriptor, wrapper, or test sources, so the exact build tool and test suite cannot be confirmed here. If the repository has a Maven wrapper, run these commands from `url-shortener/`:

```sh
./mvnw test
./mvnw package
```

If it has a Gradle wrapper instead, use the repository's Gradle tasks (commonly `./gradlew test` and `./gradlew build`). Run the application through the build tool or from the packaged Spring Boot JAR. The application entry point is `com.example.shortener.ShortenerApplication`.

The service listens on port `8080` by default. For a packaged JAR, a typical run command is:

```sh
java -jar target/<application-jar>.jar
```

Set `SERVER_PORT` or the equivalent Spring property to change the public listener. The default database directory is `./data`; run the service with a working directory where it can create and write that directory, or configure `SHORTENER_DATA_DIR`.

## Configuration

Defaults below are from `src/main/resources/application.yml`.

| Property | Environment variable | Default | Purpose |
| --- | --- | --- | --- |
| `server.port` | `SERVER_PORT` | `8080` | Public HTTP listener. |
| `shortener.data-dir` | `SHORTENER_DATA_DIR` | `./data` | Directory for the file-based H2 database. Keep this directory on persistent storage. |
| `shortener.rate-limit.creates-per-minute` | `SHORTENER_RATE_LIMIT_CREATES_PER_MINUTE` | `20` | Link creations allowed per client peer address per minute. |
| `shortener.rate-limit.failed-token-attempts-per-minute` | `SHORTENER_RATE_LIMIT_FAILED_TOKEN_ATTEMPTS_PER_MINUTE` | `10` | Wrong management-token attempts allowed per client peer address in a rolling 60-second window. |
| `shortener.max-api-body-bytes` | `SHORTENER_MAX_API_BODY_BYTES` | `16384` | Maximum request-body size for `/api/**`, in bytes. |
| `shortener.code-length` | `SHORTENER_CODE_LENGTH` | `8` | Length of generated short codes. |
| `management.server.port` | `MANAGEMENT_SERVER_PORT` | `8081` | Separate operator management listener. |
| `management.server.address` | `MANAGEMENT_SERVER_ADDRESS` | `127.0.0.1` | Address for the management listener; it is loopback-only by default. |
| `management.endpoints.web.exposure.include` | `MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE` | `health,metrics` | Actuator endpoints exposed on the management listener. |

Spring Boot accepts these settings as environment variables or configuration properties. Do not expose the management listener publicly without first reviewing the access controls and network configuration.

## Operations

### Health

`GET /health` is the public health check. It runs a database query and returns `200` with `{"status":"UP"}` when the database is reachable, or `503` with `{"status":"DOWN"}` otherwise. The Actuator health endpoint is also exposed on the management listener, normally at `http://127.0.0.1:8081/actuator/health`.

### Metrics

Actuator metrics are exposed on the management listener, normally at `http://127.0.0.1:8081/actuator/metrics`. Redirect requests are measured by the `shortener.redirects` metric, tagged only with `outcome` (`302`, `404`, `410`, `5xx`, or `other`). Its count and timer measure redirect outcomes and latency. It does not include link codes, destinations, or client identifiers. For example, query `http://127.0.0.1:8081/actuator/metrics/shortener.redirects` to inspect that metric.

### Limits and persistence

- Creation is limited per client peer address. The service uses the network peer address, not client-supplied forwarding headers.
- Wrong management tokens for statistics, deletion, and expiry updates share a per-peer-address rolling-window limit. Exceeding a limit returns `429 rate_limited` with `Retry-After`.
- Both limiters are in-memory and reset on restart. They are single-process limits, not shared across service instances.
- API request bodies are limited to 16,384 bytes by default. Oversized `/api/**` bodies return `413 payload_too_large`.
- Destination URLs must use HTTP or HTTPS, be at most 2,048 characters, and must not resolve to a prohibited local or private address. The service checks DNS at creation and does not fetch the destination. DNS changes after creation are not rechecked.
- Custom aliases use 3–32 ASCII letters, digits, underscores, or hyphens, and must not be reserved or already in use. Generated codes are 8 characters by default.
- Expiry timestamps must be strictly in the future when set. There is no maximum expiry. Expiry updates truncate timestamps to microsecond precision, matching database storage.
- Successful expiry updates commit before returning. Later metadata and redirect lookups read the persisted expiry. Redirects are not cacheable (`Cache-Control: no-store`).
- Deletion leaves a tombstone; the code stays reserved and cannot be used to create another link.
- Every response receives `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Content-Security-Policy` security headers.

## API overview

The API creates links at `POST /api/links`, returns public metadata at `GET /api/links/{code}`, and exposes private statistics and deletion on that link resource. `PATCH /api/links/{code}` sets or removes a link expiry and requires the link's `X-Management-Token`. A future `expiresAt` sets expiry; explicit JSON `null` removes it; omission is rejected. An expired link cannot be revived. Public redirects use `GET /{code}`.

See the [API reference](docs/api.md) for all operations, request and response details, errors, and curl examples. The machine-readable contract is in [`openapi.yaml`](openapi.yaml).

## Compatibility and implementation notes

Expiry updates are additive; creation, metadata, statistics, deletion, redirect, and health behavior remain as described in the API reference. The management token is returned only by link creation. The service stores its hash; updating expiry does not return or replace the token.
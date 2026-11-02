# Changelog

## [1.1.0]

### Added
- Added `PATCH /api/links/{code}` so link owners can set or remove a link’s expiry using their management token.

### Changed
- Successful expiry changes are reflected in link metadata and apply to subsequent redirects immediately. Existing endpoints retain their behavior.

### Fixed
- No unrelated fixes in this release.

### Security
- Expiry changes use the existing management-token authentication and wrong-token throttling. Invalid or unauthorized requests do not change the link.

# Changelog

## [1.2.0]

### Added
- Added support for shortening permitted HTTP(S) destinations with Unicode internationalized domain names and the reported underscore-host form.

### Changed
- Redirects use the ASCII/Punycode host when required, while preserving existing path and query escaping behavior and the exact submitted URL in `originalUrl` metadata.

### Fixed
- Fixed URL creation failures that incorrectly reported `url must include a host` for supported Unicode IDN and underscore-host destinations.

### Security
- Destination rules check the same ASCII host used for redirects, preserving rejection of prohibited destinations entered in Unicode or equivalent Punycode form.

## [1.1.0]

### Added
- Added `PATCH /api/links/{code}` so link owners can set or remove a link’s expiry using their management token.

### Changed
- Successful expiry changes are reflected in link metadata and apply to subsequent redirects immediately. Existing endpoints retain their behavior.

### Fixed
- No unrelated fixes in this release.

### Security
- Expiry changes use the existing management-token authentication and wrong-token throttling. Invalid or unauthorized requests do not change the link.

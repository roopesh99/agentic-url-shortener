# Request: split LinkService

LinkService has grown to handle creation, redirects, metadata, expiry changes, stats and deletion.
Split it into smaller services along those lines so it is easier to change. Behaviour, the API and
the database must stay exactly as they are; the existing tests must pass unchanged.

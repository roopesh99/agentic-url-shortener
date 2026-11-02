# Bug report: links to some valid websites cannot be shortened

> Input to the orchestrator's bug-fix workflow. The service in `url-shortener/` is in use.

## What users report
Support has received several reports from users who cannot shorten links to websites that open
fine in their browser. Creating the link fails immediately with:

    400 {"error":"invalid_url","message":"url must include a host"}

Examples from the tickets:
- `https://müller.de/angebote` (a German shop)
- `https://例え.jp/` (a Japanese site)
- `https://my_site.example.com/page` (an internal-looking but public host name with an underscore)

The same shop works when a user pastes its address as `https://xn--mller-kva.de/angebote`, which is
how some browsers display it when copied. Ordinary addresses such as `https://example.com/café`
work.

## Expected
Any link that a browser can open and that the service's destination rules allow can be shortened,
and its short link redirects to it. The error message should not claim that a URL with a host has
no host.

## Constraints
- The destination rules must not be weakened: links to local, private or otherwise prohibited
  addresses must still be refused, whatever form their host name is written in.
- Existing links and endpoints keep working unchanged.

## Known open points (for the Analyst to resolve or flag)
- Whether the short link should redirect to the address exactly as the user entered it, or to an
  equivalent normalized form.

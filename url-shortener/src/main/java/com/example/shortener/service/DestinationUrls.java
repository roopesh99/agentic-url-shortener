package com.example.shortener.service;

import java.net.URI;
import java.util.EnumSet;
import java.util.Set;

import com.ibm.icu.text.IDNA;

/**
 * Host handling for destination URLs. {@link URI#getHost()} is null for a host that is not plain
 * ASCII hostname syntax (an internationalized name such as {@code müller.de}, or a name with an
 * underscore), so the host is read from the authority instead. A non-ASCII host is converted to its
 * ASCII form with UTS #46, as browsers do; destination checks and redirects both use that one form,
 * so what is checked is exactly where visitors are sent. ASCII hosts are left exactly as they were.
 */
final class DestinationUrls {

    private static final IDNA UTS46 = IDNA.getUTS46Instance(IDNA.NONTRANSITIONAL_TO_ASCII
            | IDNA.NONTRANSITIONAL_TO_UNICODE | IDNA.CHECK_BIDI | IDNA.CHECK_CONTEXTJ);

    /** Browsers do not check hyphen placement (WHATWG URL: CheckHyphens = false). */
    private static final Set<IDNA.Error> IGNORED = EnumSet.of(
            IDNA.Error.LEADING_HYPHEN, IDNA.Error.TRAILING_HYPHEN, IDNA.Error.HYPHEN_3_4);

    private DestinationUrls() {
    }

    /** The host as written: the parsed host, or for an unparsed authority the part between user info and port. */
    static String host(URI uri) {
        if (uri.getHost() != null) {
            return uri.getHost();
        }
        String authority = uri.getRawAuthority();
        if (authority == null) {
            return null;
        }
        String hostAndPort = authority.substring(authority.lastIndexOf('@') + 1);
        return hostAndPort.replaceFirst(":\\d*$", "");
    }

    /** The ASCII form of a host; an ASCII host is returned unchanged. 400 invalid_url if it is not a valid name. */
    static String toAscii(String host) {
        if (isAscii(host)) {
            return host;
        }
        IDNA.Info info = new IDNA.Info();
        StringBuilder ascii = new StringBuilder();
        UTS46.nameToASCII(host, ascii, info);
        Set<IDNA.Error> errors = info.getErrors().isEmpty() ? Set.of() : EnumSet.copyOf(info.getErrors());
        if (!IGNORED.containsAll(errors)) {
            throw ApiException.badRequest("invalid_url", "url host is not a valid domain name");
        }
        return ascii.toString();
    }

    /**
     * Where a stored destination redirects to: the URL as entered, with a non-ASCII host replaced by its
     * ASCII form (a Location header must be ASCII). Nothing else is changed; non-ASCII characters in the
     * path and query are percent-encoded when the Location header is written, as before.
     */
    static String redirectTarget(String url) {
        URI uri = URI.create(url);
        String authority = uri.getRawAuthority();
        String host = host(uri);
        if (authority == null || host == null || isAscii(host)) {
            return url;
        }
        int hostStart = uri.getScheme().length() + "://".length() + authority.lastIndexOf('@') + 1;
        return url.substring(0, hostStart) + toAscii(host) + url.substring(hostStart + host.length());
    }

    private static boolean isAscii(String s) {
        return s.chars().allMatch(c -> c < 0x80);
    }
}

package com.example.shortener.service;

import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.UnknownHostException;
import java.util.Locale;

import org.springframework.stereotype.Component;

/**
 * Decides which destination URLs may be shortened (NFR2): http/https only, at most 2048
 * characters, and never a host that is, or resolves to, a loopback, private, link-local,
 * unique-local, multicast or unspecified address. DNS is checked once, at creation, and fails
 * closed. The service never fetches destinations, so later DNS changes are an accepted limitation.
 */
@Component
public class DestinationPolicy {

    static final int MAX_URL_LENGTH = 2048;

    private final HostResolver resolver;

    public DestinationPolicy(HostResolver resolver) {
        this.resolver = resolver;
    }

    /** Returns the URL unchanged if acceptable; throws a 400 {@link ApiException} otherwise. */
    public String validate(String url) {
        if (url == null || url.isBlank()) {
            throw invalid("url is required");
        }
        if (url.length() > MAX_URL_LENGTH) {
            throw invalid("url must be at most " + MAX_URL_LENGTH + " characters");
        }
        URI uri;
        try {
            uri = new URI(url);
        } catch (URISyntaxException e) {
            throw invalid("url is not a valid URI");
        }
        String scheme = uri.getScheme();
        if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
            throw invalid("only http and https URLs are allowed");
        }
        String host = uri.getHost();
        if (host == null || host.isBlank()) {
            throw invalid("url must include a host");
        }
        host = stripBrackets(host).toLowerCase(Locale.ROOT);
        if (host.equals("localhost") || host.endsWith(".localhost")) {
            throw prohibited();
        }

        InetAddress[] addresses;
        try {
            addresses = resolver.resolve(host);
        } catch (UnknownHostException | SecurityException e) {
            throw invalid("url host could not be resolved");
        }
        if (addresses == null || addresses.length == 0) {
            throw invalid("url host could not be resolved");
        }
        for (InetAddress address : addresses) {
            if (isProhibited(address)) {
                throw prohibited();
            }
        }
        return url;
    }

    static boolean isProhibited(InetAddress address) {
        if (address.isLoopbackAddress() || address.isAnyLocalAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) {
            return true;
        }
        byte[] raw = address.getAddress();
        if (address instanceof Inet6Address) {
            // fc00::/7 unique-local (Java's isSiteLocalAddress only covers the deprecated fec0::/10)
            return (raw[0] & 0xfe) == 0xfc;
        }
        return false;
    }

    private static String stripBrackets(String host) {
        return host.startsWith("[") && host.endsWith("]") ? host.substring(1, host.length() - 1) : host;
    }

    private static ApiException invalid(String message) {
        return ApiException.badRequest("invalid_url", message);
    }

    private static ApiException prohibited() {
        return ApiException.badRequest("prohibited_destination",
                "url points to a local, private or otherwise prohibited address");
    }
}

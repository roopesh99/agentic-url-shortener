package com.example.shortener.support;

import java.util.Map;

/** The browser-hardening headers every response must carry (FR13). */
public final class SecurityHeaders {

    public static final Map<String, String> EXPECTED = Map.of(
            "X-Content-Type-Options", "nosniff",
            "X-Frame-Options", "DENY",
            "Referrer-Policy", "no-referrer",
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");

    private SecurityHeaders() {
    }
}

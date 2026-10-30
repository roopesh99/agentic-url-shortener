package com.example.shortener;

import java.net.URI;
import java.security.SecureRandom;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Service;

/** In-memory skeleton implementation: Base62 codes, http/https only. */
@Service
public class ShortUrlService {

    static final int CODE_LENGTH = 7;
    private static final String ALPHABET =
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

    private final SecureRandom random = new SecureRandom();
    private final Map<String, String> store = new ConcurrentHashMap<>();

    public String shorten(String url) {
        validate(url);
        while (true) {
            String code = randomCode();
            if (store.putIfAbsent(code, url) == null) {
                return code;
            }
        }
    }

    public Optional<String> resolve(String code) {
        return Optional.ofNullable(store.get(code));
    }

    private static void validate(String url) {
        URI uri;
        try {
            uri = URI.create(url);
        } catch (IllegalArgumentException | NullPointerException e) {
            throw new IllegalArgumentException("malformed URL");
        }
        String scheme = uri.getScheme();
        if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
            throw new IllegalArgumentException("only http and https URLs are allowed");
        }
        if (uri.getHost() == null) {
            throw new IllegalArgumentException("URL must have a host");
        }
    }

    private String randomCode() {
        StringBuilder sb = new StringBuilder(CODE_LENGTH);
        for (int i = 0; i < CODE_LENGTH; i++) {
            sb.append(ALPHABET.charAt(random.nextInt(ALPHABET.length())));
        }
        return sb.toString();
    }
}

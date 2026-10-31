package com.example.shortener.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

import org.springframework.stereotype.Component;

/**
 * Management tokens: 256 random bits, unpadded base64url. Only the SHA-256 hash is stored;
 * the plaintext exists solely in the creation response.
 */
@Component
public class TokenService {

    private final SecureRandom random;

    public TokenService(SecureRandom random) {
        this.random = random;
    }

    public String newToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public String hash(String token) {
        return HexFormat.of().formatHex(sha256(token));
    }

    /** Constant-time comparison, so response timing reveals nothing about the stored hash. */
    public boolean matches(String token, String storedHash) {
        if (token == null || storedHash == null) {
            return false;
        }
        byte[] expected;
        try {
            expected = HexFormat.of().parseHex(storedHash);
        } catch (IllegalArgumentException e) {
            return false;
        }
        return MessageDigest.isEqual(sha256(token), expected);
    }

    private static byte[] sha256(String value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}

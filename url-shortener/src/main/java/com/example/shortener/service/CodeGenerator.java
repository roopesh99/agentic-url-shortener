package com.example.shortener.service;

import java.security.SecureRandom;

import com.example.shortener.config.ShortenerProperties;
import org.springframework.stereotype.Component;

/** Cryptographically random short codes from the URL-safe alphabet [A-Za-z0-9_-]. */
@Component
public class CodeGenerator {

    private static final char[] ALPHABET =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-".toCharArray();

    private final SecureRandom random;
    private final int length;

    public CodeGenerator(SecureRandom random, ShortenerProperties properties) {
        this.random = random;
        this.length = properties.codeLength();
    }

    public String next() {
        char[] code = new char[length];
        for (int i = 0; i < length; i++) {
            code[i] = ALPHABET[random.nextInt(ALPHABET.length)];
        }
        return new String(code);
    }
}

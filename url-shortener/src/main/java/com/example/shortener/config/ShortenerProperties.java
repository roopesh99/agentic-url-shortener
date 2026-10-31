package com.example.shortener.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param dataDir    directory holding the file-based H2 database
 * @param rateLimit  link-creation rate limit per client IP
 * @param codeLength length of generated short codes
 */
@ConfigurationProperties(prefix = "shortener")
public record ShortenerProperties(String dataDir, RateLimit rateLimit, int codeLength) {

    public record RateLimit(int createsPerMinute) {
    }
}

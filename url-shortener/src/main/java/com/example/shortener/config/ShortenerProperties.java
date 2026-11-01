package com.example.shortener.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param dataDir         directory holding the file-based H2 database
 * @param rateLimit       per-client-IP limits
 * @param codeLength      length of generated short codes
 * @param maxApiBodyBytes largest request body accepted on /api/**
 */
@ConfigurationProperties(prefix = "shortener")
public record ShortenerProperties(String dataDir, RateLimit rateLimit, int codeLength, int maxApiBodyBytes) {

    /**
     * @param createsPerMinute             link creations per client IP per minute
     * @param failedTokenAttemptsPerMinute wrong management tokens per client IP per rolling minute
     */
    public record RateLimit(int createsPerMinute, int failedTokenAttemptsPerMinute) {
    }
}

package com.example.shortener.service;

import org.springframework.http.HttpStatus;

public class RateLimitedException extends ApiException {

    public RateLimitedException(long retryAfterSeconds) {
        this(retryAfterSeconds, "too many links created; retry later");
    }

    public RateLimitedException(long retryAfterSeconds, String message) {
        super(HttpStatus.TOO_MANY_REQUESTS, "rate_limited", message, retryAfterSeconds);
    }
}

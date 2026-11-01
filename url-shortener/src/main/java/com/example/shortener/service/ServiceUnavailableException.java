package com.example.shortener.service;

import org.springframework.http.HttpStatus;

/** The database could not serve a redirect (FR6): 503 with a fixed Retry-After, never retried here. */
public class ServiceUnavailableException extends ApiException {

    static final long RETRY_AFTER_SECONDS = 5;

    public ServiceUnavailableException() {
        super(HttpStatus.SERVICE_UNAVAILABLE, "service_unavailable", "the service is temporarily unavailable; retry later",
                RETRY_AFTER_SECONDS);
    }
}

package com.example.shortener.service;

import java.time.Clock;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import com.example.shortener.config.ShortenerProperties;
import org.springframework.stereotype.Component;

/**
 * Throttles management-token guessing (FR10): at most N wrong tokens per client IP in a rolling
 * 60-second window, shared by the stats, delete and expiry-change endpoints. Only supplied-but-wrong tokens count;
 * a missing token is a client bug, not a guess, and a valid token is never blocked.
 * In memory and single-node by design; reset on restart.
 */
@Component
public class ManagementTokenRateLimiter {

    static final long WINDOW_MILLIS = 60_000;
    private static final int SWEEP_EVERY = 1024;

    private final Map<String, Deque<Long>> failures = new ConcurrentHashMap<>();
    private final AtomicLong records = new AtomicLong();
    private final int limit;
    private final Clock clock;

    public ManagementTokenRateLimiter(ShortenerProperties properties, Clock clock) {
        this.limit = properties.rateLimit().failedTokenAttemptsPerMinute();
        this.clock = clock;
    }

    /**
     * Records one wrong token from this client. Returns normally while the client is within the limit
     * (the caller then answers 403 invalid_token); throws 429 rate_limited once it is exceeded.
     */
    public void recordFailure(String clientAddress) {
        long now = clock.millis();
        Deque<Long> attempts = failures.computeIfAbsent(clientAddress, k -> new ArrayDeque<>());
        long retryAfterMillis = -1;
        synchronized (attempts) {
            prune(attempts, now);
            attempts.addLast(now);
            if (attempts.size() > limit) {
                retryAfterMillis = attempts.peekFirst() + WINDOW_MILLIS - now;
            }
        }
        if (records.incrementAndGet() % SWEEP_EVERY == 0) {
            sweep(now);
        }
        if (retryAfterMillis >= 0) {
            throw new RateLimitedException(Math.max(1, (retryAfterMillis + 999) / 1000),
                    "too many invalid management tokens; retry later");
        }
    }

    private static void prune(Deque<Long> attempts, long now) {
        while (!attempts.isEmpty() && attempts.peekFirst() <= now - WINDOW_MILLIS) {
            attempts.removeFirst();
        }
    }

    /** Drops clients with no attempts left in the window, so memory follows active clients only. */
    private void sweep(long now) {
        failures.entrySet().removeIf(entry -> {
            synchronized (entry.getValue()) {
                prune(entry.getValue(), now);
                return entry.getValue().isEmpty();
            }
        });
    }
}

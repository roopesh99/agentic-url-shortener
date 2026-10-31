package com.example.shortener.service;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.TimeUnit;

import com.example.shortener.config.ShortenerProperties;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.ConsumptionProbe;
import org.springframework.stereotype.Component;

/**
 * In-memory per-client-IP limit on link creation (NFR3): N creates per minute, refilled once a
 * minute. State is lost on restart by design. One bucket is kept per distinct client address;
 * that is fine for a single-node service but would need eviction or a shared store at scale.
 */
@Component
public class CreateRateLimiter {

    private final ConcurrentMap<String, Bucket> buckets = new ConcurrentHashMap<>();
    private final int perMinute;

    public CreateRateLimiter(ShortenerProperties properties) {
        this.perMinute = properties.rateLimit().createsPerMinute();
    }

    /** Consumes one create for this client, or throws 429 with a Retry-After in seconds. */
    public void acquire(String clientAddress) {
        ConsumptionProbe probe = buckets.computeIfAbsent(clientAddress, k -> newBucket()).tryConsumeAndReturnRemaining(1);
        if (!probe.isConsumed()) {
            long seconds = Math.max(1, TimeUnit.NANOSECONDS.toSeconds(probe.getNanosToWaitForRefill() + 999_999_999L));
            throw new RateLimitedException(seconds);
        }
    }

    private Bucket newBucket() {
        Bandwidth limit = Bandwidth.builder()
                .capacity(perMinute)
                .refillIntervally(perMinute, Duration.ofMinutes(1))
                .build();
        return Bucket.builder().addLimit(limit).build();
    }
}

package com.example.shortener.api;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Redirect observability (FR14): one timer, shortener.redirects, tagged only with the outcome
 * (302, 404, 410, 5xx; anything else is "other"). Its count is the per-outcome count and its timing the
 * redirect latency. No code, destination or client tags, and no extra work on the hot path.
 */
@Component
public class RedirectMetricsInterceptor implements HandlerInterceptor {

    static final String METRIC = "shortener.redirects";
    private static final String STARTED = RedirectMetricsInterceptor.class.getName() + ".started";

    private final MeterRegistry registry;
    private final Map<String, Timer> timers = new ConcurrentHashMap<>();

    public RedirectMetricsInterceptor(MeterRegistry registry) {
        this.registry = registry;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (isRedirect(handler)) {
            request.setAttribute(STARTED, System.nanoTime());
        }
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        if (request.getAttribute(STARTED) instanceof Long started) {
            String outcome = outcome(response.getStatus());
            timers.computeIfAbsent(outcome, o -> Timer.builder(METRIC).tag("outcome", o)
                            .description("Redirect requests by outcome").register(registry))
                    .record(System.nanoTime() - started, TimeUnit.NANOSECONDS);
        }
    }

    static String outcome(int status) {
        return switch (status) {
            case 302 -> "302";
            case 404 -> "404";
            case 410 -> "410";
            default -> status >= 500 ? "5xx" : "other";
        };
    }

    private static boolean isRedirect(Object handler) {
        return handler instanceof HandlerMethod method && method.getBeanType() == RedirectController.class;
    }
}

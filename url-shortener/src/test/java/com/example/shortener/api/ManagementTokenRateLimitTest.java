package com.example.shortener.api;

import static com.example.shortener.api.ErrorContractAndHeadersTest.peer;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.config.ShortenerProperties;
import com.example.shortener.service.ManagementTokenRateLimiter;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

/**
 * FR10: at most 10 wrong management tokens per client IP per rolling minute, shared by stats, delete
 * and expiry changes.
 */
class ManagementTokenRateLimitTest extends IntegrationTest {

    private static final AtomicInteger NEXT = new AtomicInteger(1);

    // --- unit: the rolling window --------------------------------------------------------------

    @Test
    void TC_FR10_01_tenWrongTokensAreAdmittedTheEleventhIsLimitedUntilTheWindowRolls() {
        MutableClock time = new MutableClock();
        ManagementTokenRateLimiter limiter = new ManagementTokenRateLimiter(
                new ShortenerProperties("./data", new ShortenerProperties.RateLimit(20, 10), 8, 16_384), time);
        for (int i = 0; i < 10; i++) {
            time.advance(Duration.ofSeconds(1));
            limiter.recordFailure("192.0.2.1"); // attempts at t = 1 .. 10 s
        }
        assertThatThrownBy(() -> limiter.recordFailure("192.0.2.1"))
                .isInstanceOfSatisfying(RateLimitedException.class, e -> {
                    assertThat(e.getError()).isEqualTo("rate_limited");
                    assertThat(e.getRetryAfterSeconds()).isEqualTo(51L); // until the t=1s attempt leaves the window
                });
        assertThatCode(() -> limiter.recordFailure("192.0.2.2")).as("another peer is unaffected").doesNotThrowAnyException();

        time.advance(Duration.ofSeconds(61)); // every attempt (including the rejected ones) has left the window
        assertThatCode(() -> limiter.recordFailure("192.0.2.1")).doesNotThrowAnyException();
    }

    // --- integration: through stats and delete --------------------------------------------------

    @Test
    void TC_FR10_02_wrongTokensAcrossStatsAndDeleteShareOneLimit() throws Exception {
        JsonNode link = create("https://example.com/limit");
        String code = link.get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 10; i++) {
            var request = i % 2 == 0 ? get("/api/links/" + code + "/stats") : delete("/api/links/" + code);
            mvc.perform(request.header("X-Management-Token", "wrong").with(peer(ip)))
                    .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("invalid_token"));
        }
        mvc.perform(delete("/api/links/" + code).header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error").value("rate_limited"))
                .andExpect(header().exists("Retry-After"));
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests());
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isFalse();
    }

    @Test
    void TC_FR2_03_wrongTokensOnExpiryChangesCountTowardTheSameLimit() throws Exception {
        JsonNode link = create("https://example.com/limit-patch", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 10; i++) {
            var request = i % 2 == 0 ? expiryChange(code) : get("/api/links/" + code + "/stats");
            mvc.perform(request.header("X-Management-Token", "wrong").with(peer(ip)))
                    .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("invalid_token"));
        }
        mvc.perform(expiryChange(code).header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error").value("rate_limited"))
                .andExpect(header().exists("Retry-After"));
        mvc.perform(delete("/api/links/" + code).header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isTooManyRequests()); // the PATCH failures counted for delete too
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isNotNull();

        mvc.perform(expiryChange(code).header("X-Management-Token", link.get("managementToken").asText()).with(peer(ip)))
                .andExpect(status().isOk()); // the real owner is never locked out
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isNull();
    }

    @Test
    void TC_FR10_02_missingTokensNeverCount() throws Exception {
        String code = create("https://example.com/missing").get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 25; i++) {
            mvc.perform(get("/api/links/" + code + "/stats").with(peer(ip)))
                    .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("missing_token"));
        }
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)))
                .andExpect(status().isForbidden());
    }

    @Test
    void TC_FR10_02_validTokenStillWorksWhileTheIpIsLimitedAndForwardedForIsIgnored() throws Exception {
        JsonNode link = create("https://example.com/owner");
        String code = link.get("code").asText();
        String ip = freshIp();
        for (int i = 0; i < 11; i++) {
            mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip)));
        }
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", "wrong").with(peer(ip))
                        .header("X-Forwarded-For", "203.0.113.200"))
                .andExpect(status().isTooManyRequests()); // a spoofed header does not escape the limit
        mvc.perform(get("/api/links/" + code + "/stats").header("X-Management-Token", link.get("managementToken").asText())
                        .with(peer(ip)))
                .andExpect(status().isOk()); // the real owner is never locked out
    }

    private static org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder expiryChange(String code) {
        return patch("/api/links/" + code).contentType(MediaType.APPLICATION_JSON).content("{\"expiresAt\":null}");
    }

    private static String freshIp() {
        return "198.18.200." + NEXT.getAndIncrement();
    }
}

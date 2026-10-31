package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.concurrent.atomic.AtomicInteger;

import com.example.shortener.config.ShortenerProperties;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.TestSupportConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/** NFR3 with the production limit of 20 creates per minute per peer IP. */
@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:ratelimit-${random.uuid};DB_CLOSE_DELAY=-1")
@AutoConfigureMockMvc
@Import(TestSupportConfig.class)
class RateLimitTest {

    private static final AtomicInteger NEXT_IP = new AtomicInteger(1);

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ShortenerProperties properties;

    @Test
    void TC_NFR3_01_twentyCreatesPerMinuteThen429WithRetryAfter() throws Exception {
        assertThat(properties.rateLimit().createsPerMinute()).isEqualTo(20);
        String ip = freshIp();
        for (int i = 0; i < 20; i++) {
            createFrom(ip, null).andExpect(status().isCreated());
        }
        createFrom(ip, null)
                .andExpect(status().isTooManyRequests())
                .andExpect(header().exists("Retry-After"))
                .andExpect(result -> assertThat(Long.parseLong(result.getResponse().getHeader("Retry-After")))
                        .isBetween(1L, 60L));
    }

    @Test
    void TC_NFR3_02_bucketsArePerPeerIpAndIgnoreXForwardedFor() throws Exception {
        String exhausted = freshIp();
        for (int i = 0; i < 20; i++) {
            createFrom(exhausted, null).andExpect(status().isCreated());
        }
        createFrom(exhausted, "203.0.113.99").andExpect(status().isTooManyRequests()); // spoofed header: same bucket
        createFrom(freshIp(), null).andExpect(status().isCreated());                   // another peer: unaffected
    }

    @Test
    void TC_NFR3_03_rejectedAttemptsConsumeTokens() throws Exception {
        String ip = freshIp();
        mvc.perform(post("/api/links").with(peer(ip)).contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"ftp://example.com/invalid\"}")).andExpect(status().isBadRequest());
        for (int i = 0; i < 19; i++) {
            createFrom(ip, null).andExpect(status().isCreated());
        }
        createFrom(ip, null).andExpect(status().isTooManyRequests());
    }

    /**
     * TC-NFR3-03 (restart): limiter state is in memory only, so a new instance, which is what a
     * restart creates, starts with a full bucket. The full application restart is covered in
     * PersistenceRestartTest.
     */
    @Test
    void TC_NFR3_03_freshLimiterAfterRestartAllowsTheIpAgain() {
        CreateRateLimiter beforeRestart = new CreateRateLimiter(properties);
        for (int i = 0; i < 20; i++) {
            beforeRestart.acquire("198.51.100.7");
        }
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> beforeRestart.acquire("198.51.100.7"))
                .isInstanceOf(RateLimitedException.class);

        new CreateRateLimiter(properties).acquire("198.51.100.7"); // does not throw
    }

    private ResultActions createFrom(String ip, String forwardedFor) throws Exception {
        var request = post("/api/links").with(peer(ip)).contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"https://example.com/rl\"}");
        if (forwardedFor != null) {
            request.header("X-Forwarded-For", forwardedFor);
        }
        return mvc.perform(request);
    }

    private static org.springframework.test.web.servlet.request.RequestPostProcessor peer(String ip) {
        return request -> {
            request.setRemoteAddr(ip);
            return request;
        };
    }

    private static String freshIp() {
        int n = NEXT_IP.getAndIncrement();
        return "198.18." + (n / 250) + "." + (n % 250 + 1);
    }
}

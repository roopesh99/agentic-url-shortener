package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.util.Collection;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.ServiceUnavailableException;
import com.example.shortener.support.IntegrationTest;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

/** FR6 (database outage on redirect), FR11 and FR14 (redirect outcome metrics, no probing limit). */
class RedirectOutageAndMetricsTest extends IntegrationTest {

    @Autowired
    private MeterRegistry registry;

    @Test
    void TC_FR14_01_eachRedirectOutcomeIsCountedAndTimedWithOnlyAnOutcomeTag() throws Exception {
        JsonNode active = create("https://example.com/m-active");
        JsonNode doomed = create("https://example.com/m-deleted");
        JsonNode expiring = create("https://example.com/m-expired", null, "2030-01-01T00:00:01Z");
        long ok = count("302"), notFound = count("404"), gone = count("410");

        mvc.perform(get("/" + active.get("code").asText())).andExpect(status().isFound());
        mvc.perform(get("/" + active.get("code").asText())).andExpect(status().isFound());
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound());
        mvc.perform(delete("/api/links/" + doomed.get("code").asText())
                .header("X-Management-Token", doomed.get("managementToken").asText())).andExpect(status().isNoContent());
        mvc.perform(get("/" + doomed.get("code").asText())).andExpect(status().isNotFound());
        clock.advance(Duration.ofSeconds(5));
        mvc.perform(get("/" + expiring.get("code").asText())).andExpect(status().isGone());

        assertThat(count("302") - ok).isEqualTo(2);
        assertThat(count("404") - notFound).as("unknown and deleted share one aggregate outcome").isEqualTo(2);
        assertThat(count("410") - gone).isEqualTo(1);
        Timer timer = registry.get(RedirectMetricsInterceptor.METRIC).tag("outcome", "302").timer();
        assertThat(timer.totalTime(java.util.concurrent.TimeUnit.NANOSECONDS)).isPositive();
        assertThat(timer.getId().getTags()).extracting(t -> t.getKey()).containsExactly("outcome");
    }

    @Test
    void TC_FR11_01_repeatedUnknownCodesAreNotRateLimited() throws Exception {
        long before = count("404");
        for (int i = 0; i < 60; i++) {
            mvc.perform(get("/Probe" + String.format("%03d", i))).andExpect(status().isNotFound());
        }
        assertThat(count("404") - before).isEqualTo(60);
    }

    @Test
    void TC_FR14_01_nonRedirectRequestsAreNotCounted() throws Exception {
        long all = allCounts();
        mvc.perform(get("/health"));
        mvc.perform(get("/api/links/Zz9Zz9Zz"));
        mvc.perform(get("/no/such/route"));
        assertThat(allCounts()).isEqualTo(all);
    }

    @Test
    void TC_FR14_01_outcomeMapping() {
        assertThat(RedirectMetricsInterceptor.outcome(302)).isEqualTo("302");
        assertThat(RedirectMetricsInterceptor.outcome(503)).isEqualTo("5xx");
        assertThat(RedirectMetricsInterceptor.outcome(500)).isEqualTo("5xx");
        assertThat(RedirectMetricsInterceptor.outcome(429)).isEqualTo("other");
    }

    /** TC-FR6-01 at the controller: each kind of "the link store cannot answer" becomes the 503. */
    @ParameterizedTest
    @ValueSource(strings = {"resource", "transient", "transaction"})
    void TC_FR6_01_storeFailuresDuringTheLookupBecome503(String kind) {
        LinkService links = mock(LinkService.class);
        RuntimeException failure = switch (kind) {
            case "resource" -> new DataAccessResourceFailureException("db down");
            case "transient" -> new QueryTimeoutException("db slow");
            default -> new CannotCreateTransactionException("no connection");
        };
        when(links.resolve("abc12345")).thenThrow(failure);
        org.assertj.core.api.Assertions.assertThatThrownBy(
                () -> new RedirectController(links, mock(ClickRecorder.class)).redirect("abc12345"))
                .isInstanceOfSatisfying(ServiceUnavailableException.class, e -> {
                    assertThat(e.getError()).isEqualTo("service_unavailable");
                    assertThat(e.getRetryAfterSeconds()).isEqualTo(5L);
                });
    }

    /** TC-FR6-01 through HTTP, and its 5xx metric outcome. */
    @Nested
    class WhenTheLinkStoreIsDown extends IntegrationTest {

        @MockitoBean
        private LinkService links;

        @Autowired
        private MeterRegistry registry;

        @Test
        void TC_FR6_01_redirectReturns503WithRetryAfterFiveAndIsCountedAs5xx() throws Exception {
            when(links.resolve(anyString())).thenThrow(new CannotCreateTransactionException("connection refused"));
            long before = countIn(registry, "5xx");
            mvc.perform(get("/abc12345"))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(header().string("Retry-After", "5"))
                    .andExpect(header().doesNotExist("Location"))
                    .andExpect(jsonPath("$.error").value("service_unavailable"))
                    .andExpect(result -> assertThat(result.getResponse().getContentAsString()).doesNotContain("connection refused"));
            assertThat(countIn(registry, "5xx") - before).isEqualTo(1);
        }
    }

    private long count(String outcome) {
        return countIn(registry, outcome);
    }

    private long allCounts() {
        Collection<Timer> timers = registry.find(RedirectMetricsInterceptor.METRIC).timers();
        return timers.stream().mapToLong(Timer::count).sum();
    }

    static long countIn(MeterRegistry registry, String outcome) {
        Timer timer = registry.find(RedirectMetricsInterceptor.METRIC).tag("outcome", outcome).timer();
        return timer == null ? 0 : timer.count();
    }
}

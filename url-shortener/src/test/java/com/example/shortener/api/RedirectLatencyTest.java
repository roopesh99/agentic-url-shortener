package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import java.util.Arrays;

import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;

/**
 * TC-NFR1-01: indicative, in-process latency check (not a production SLO). 1,000 sequential
 * warm-up redirects, then 1,000 measured ones from a single client on the local machine.
 */
class RedirectLatencyTest extends IntegrationTest {

    @Test
    void TC_NFR1_01_redirectP99IsBelow50ms() throws Exception {
        String code = create("https://example.com/tc-nfr1-01").get("code").asText();
        for (int i = 0; i < 1_000; i++) {
            assertThat(mvc.perform(get("/" + code)).andReturn().getResponse().getStatus()).isEqualTo(302);
        }

        long[] nanos = new long[1_000];
        for (int i = 0; i < nanos.length; i++) {
            long start = System.nanoTime();
            int status = mvc.perform(get("/" + code)).andReturn().getResponse().getStatus();
            nanos[i] = System.nanoTime() - start;
            assertThat(status).isEqualTo(302);
        }
        Arrays.sort(nanos);
        double p99Millis = nanos[(int) Math.ceil(0.99 * nanos.length) - 1] / 1_000_000.0;
        System.out.printf("TC-NFR1-01 redirect latency: p50=%.3f ms, p99=%.3f ms%n",
                nanos[nanos.length / 2] / 1_000_000.0, p99Millis);
        assertThat(p99Millis).isLessThan(50.0);
    }
}

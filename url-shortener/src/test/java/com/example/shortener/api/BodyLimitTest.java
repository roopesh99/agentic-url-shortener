package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.config.ApiBodyLimitFilter;
import com.example.shortener.support.IntegrationTest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/** FR12: at most 16,384 bytes of request body on /api/**, measured on the bytes actually received. */
class BodyLimitTest extends IntegrationTest {

    @Test
    void TC_FR12_01_bodyOfExactly16384BytesIsAcceptedAnd16385IsRejected() throws Exception {
        mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON).content(jsonOfSize(16_384)))
                .andExpect(status().isCreated());
        mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON).content(jsonOfSize(16_385)))
                .andExpect(status().isPayloadTooLarge());
    }

    /** A request that does not declare its length (chunked): the filter must count what it reads. */
    @Test
    void TC_FR12_01_undeclaredLengthIsMeasuredOnBytesReceived() throws Exception {
        ApiBodyLimitFilter filter = new ApiBodyLimitFilter(16_384, new ObjectMapper());
        AtomicReference<byte[]> forwarded = new AtomicReference<>();

        MockHttpServletResponse rejected = run(filter, jsonOfSize(16_385), forwarded);
        assertThat(rejected.getStatus()).isEqualTo(413);
        assertThat(rejected.getContentAsString()).contains("\"error\":\"payload_too_large\"");
        assertThat(forwarded.get()).as("an oversized body never reaches the application").isNull();

        byte[] ok = jsonOfSize(16_384);
        MockHttpServletResponse accepted = run(filter, ok, forwarded);
        assertThat(accepted.getStatus()).isEqualTo(200);
        assertThat(forwarded.get()).as("a body within the limit is passed on unchanged").isEqualTo(ok);
    }

    @Test
    void TC_FR12_01_onlyApiPathsAreLimited() throws Exception {
        ApiBodyLimitFilter filter = new ApiBodyLimitFilter(10, new ObjectMapper());
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/health");
        request.setContent(new byte[100]);
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> ((MockHttpServletResponse) res).setStatus(200));
        assertThat(response.getStatus()).isEqualTo(200);
    }

    private static MockHttpServletResponse run(ApiBodyLimitFilter filter, byte[] body, AtomicReference<byte[]> seen)
            throws Exception {
        seen.set(null);
        MockHttpServletRequest raw = new MockHttpServletRequest("POST", "/api/links");
        raw.setContent(body);
        var undeclared = new HttpServletRequestWrapper(raw) {
            @Override
            public long getContentLengthLong() {
                return -1; // as with Transfer-Encoding: chunked
            }

            @Override
            public int getContentLength() {
                return -1;
            }
        };
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(undeclared, response, (req, res) -> {
            seen.set(req.getInputStream().readAllBytes());
            ((MockHttpServletResponse) res).setStatus(200);
        });
        return response;
    }

    /** A valid create request padded with JSON whitespace to exactly {@code size} bytes. */
    private static byte[] jsonOfSize(int size) {
        String core = "{\"url\":\"https://example.com/body-limit\"}";
        return (core + " ".repeat(size - core.length())).getBytes(StandardCharsets.UTF_8);
    }
}

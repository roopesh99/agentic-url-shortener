package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.SecurityHeaders;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;

/** FR4, FR7, FR8, FR13: the error contract (existing codes kept, new ones standard) and security headers. */
class ErrorContractAndHeadersTest extends IntegrationTest {

    @Test
    void TC_FR4_01_existingTokenContractIsUnchangedBelowTheLimit() throws Exception {
        JsonNode link = create("https://example.com/fr4");
        String code = link.get("code").asText();
        for (String path : new String[] {"/api/links/" + code + "/stats", "/api/links/" + code}) {
            boolean isDelete = !path.endsWith("/stats");
            mvc.perform(isDelete ? delete(path) : get(path))
                    .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("missing_token"));
            mvc.perform((isDelete ? delete(path) : get(path)).header("X-Management-Token", "wrong")
                    .with(peer("198.51.100.40")))
                    .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("invalid_token"));
        }
    }

    @Test
    void TC_FR8_01_frameworkErrorsUseTheStandardBody() throws Exception {
        assertStandardError(mvc.perform(get("/no/such/route")).andExpect(status().isNotFound()), "not_found");
        assertStandardError(mvc.perform(put("/api/links")).andExpect(status().isMethodNotAllowed())
                .andExpect(header().string("Allow", "POST")), "method_not_allowed");
        assertStandardError(mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content("{\"url\":\"https://example.com/" + "a".repeat(17_000) + "\"}"))
                .andExpect(status().isPayloadTooLarge()), "payload_too_large");
        assertStandardError(mvc.perform(post("/api/links").contentType(MediaType.TEXT_PLAIN).content("x"))
                .andExpect(status().isUnsupportedMediaType()), "unsupported_media_type");
    }

    @Test
    void TC_FR8_01_existingApplicationErrorCodesAreUnchanged() throws Exception {
        assertStandardError(postLink(Map.of("url", "ftp://example.com")).andExpect(status().isBadRequest()), "invalid_url");
        String alias = uniqueAlias("dup");
        create("https://example.com/dup", alias, null);
        assertStandardError(postLink(Map.of("url", "https://example.com/dup2", "alias", alias))
                .andExpect(status().isConflict()), "alias_taken");
        assertStandardError(mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()), "not_found");
        JsonNode expiring = create("https://example.com/exp", null, "2030-01-01T00:00:01Z");
        clock.advance(java.time.Duration.ofSeconds(5));
        assertStandardError(mvc.perform(get("/" + expiring.get("code").asText())).andExpect(status().isGone()), "expired");
    }

    @Test
    void TC_FR13_01_everyResponseCarriesTheSecurityHeaders() throws Exception {
        JsonNode link = create("https://example.com/headers");
        String code = link.get("code").asText();
        assertSecurityHeaders(mvc.perform(get("/" + code)).andExpect(status().isFound()));             // redirect
        assertSecurityHeaders(mvc.perform(get("/api/links/" + code)).andExpect(status().isOk()));      // success
        assertSecurityHeaders(mvc.perform(get("/health")).andExpect(status().isOk()));                 // public health
        assertSecurityHeaders(mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()));        // app error
        assertSecurityHeaders(mvc.perform(get("/no/such/route")).andExpect(status().isNotFound()));   // framework error
        assertSecurityHeaders(mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content("x".repeat(17_000))).andExpect(status().isPayloadTooLarge()));                // rejected by a filter
    }

    @Test
    void TC_FR16_01_publicHealthIsUnchanged() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("UP"))
                .andExpect(result -> assertThat(json.readTree(result.getResponse().getContentAsString()).size()).isEqualTo(1));
    }

    /** FR7: an unexpected exception becomes a fixed 500 with nothing from the exception in the response. */
    @Nested
    class WhenSomethingUnexpectedBreaks extends IntegrationTest {

        @MockitoBean
        private LinkService links;

        @Test
        void TC_FR7_01_unexpectedErrorIsA500WithNoInternals() throws Exception {
            when(links.metadata(anyString())).thenThrow(
                    new IllegalStateException("SECRET-DETAIL at com.example.Internal.method(Internal.java:42)"));
            MvcResult result = mvc.perform(get("/api/links/abc12345")).andExpect(status().isInternalServerError())
                    .andExpect(jsonPath("$.error").value("internal_error")).andReturn();
            String body = result.getResponse().getContentAsString();
            assertThat(body).doesNotContain("SECRET-DETAIL").doesNotContain("Internal.java").doesNotContain("Exception");
            assertSecurityHeaders(result);
        }
    }

    static void assertStandardError(ResultActions actions, String code) throws Exception {
        MvcResult result = actions.andReturn();
        JsonNode body = new com.fasterxml.jackson.databind.ObjectMapper().readTree(result.getResponse().getContentAsString());
        Set<String> fields = new HashSet<>();
        body.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("error", "message");
        assertThat(body.get("error").asText()).isEqualTo(code);
        assertThat(result.getResponse().getContentType()).startsWith("application/json");
    }

    static void assertSecurityHeaders(ResultActions actions) throws Exception {
        assertSecurityHeaders(actions.andReturn());
    }

    static void assertSecurityHeaders(MvcResult result) {
        SecurityHeaders.EXPECTED.forEach((name, value) -> assertThat(result.getResponse().getHeader(name)).as(name).isEqualTo(value));
    }

    static org.springframework.test.web.servlet.request.RequestPostProcessor peer(String ip) {
        return request -> {
            request.setRemoteAddr(ip);
            return request;
        };
    }
}

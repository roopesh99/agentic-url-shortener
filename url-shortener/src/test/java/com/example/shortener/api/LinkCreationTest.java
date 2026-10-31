package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class LinkCreationTest extends IntegrationTest {

    @Test
    void TC_FR1_01_generatedCodeCreationResponse() throws Exception {
        postLink(Map.of("url", "http://example.com/tc-fr1-01"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.code").value(matchesPattern("[A-Za-z0-9_-]{8}")))
                .andExpect(jsonPath("$.shortPath").value(matchesPattern("/[A-Za-z0-9_-]{8}")))
                .andExpect(jsonPath("$.managementToken").isNotEmpty());

        JsonNode created = create("https://example.com/tc-fr1-01b");
        assertThat(created.get("shortPath").asText()).isEqualTo("/" + created.get("code").asText());
    }

    @Test
    void TC_FR1_02_customAliasIsUsedExactlyAndCaseSensitively() throws Exception {
        String alias = uniqueAlias("MiXeD");
        JsonNode created = create("https://example.com/tc-fr1-02", alias, null);
        assertThat(created.get("code").asText()).isEqualTo(alias);
        assertThat(created.get("shortPath").asText()).isEqualTo("/" + alias);

        // a different-case spelling is a distinct alias, not a conflict
        create("https://example.com/tc-fr1-02b", alias.toLowerCase(), null);
    }

    @ParameterizedTest
    @ValueSource(strings = {"ab", "a234567890123456789012345678901234", "has space", "dot.ted", "slash/x", "ünï",
            "api", "health", "links", "API", "Health"})
    void TC_FR1_03_invalidOrReservedAliasIsRejected(String alias) throws Exception {
        long before = repository.count();
        postLink(Map.of("url", "https://example.com/tc-fr1-03", "alias", alias)).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_FR1_03_boundaryAliasLengthsAreAccepted() throws Exception {
        create("https://example.com/tc-fr1-03-min", "x" + uniqueAlias("").substring(1, 3), null);
        create("https://example.com/tc-fr1-03-max", ("max-" + uniqueAlias("") + "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").substring(0, 32), null);
    }

    @Test
    void TC_FR1_04_aliasOfActiveLinkOrTombstoneConflicts() throws Exception {
        String active = uniqueAlias("taken");
        create("https://example.com/tc-fr1-04", active, null);
        postLink(Map.of("url", "https://example.com/other", "alias", active)).andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("alias_taken"));

        String deleted = uniqueAlias("tomb");
        JsonNode created = create("https://example.com/tc-fr1-04b", deleted, null);
        mvc.perform(delete("/api/links/" + deleted)
                .header("X-Management-Token", created.get("managementToken").asText())).andExpect(status().isNoContent());
        postLink(Map.of("url", "https://example.com/other", "alias", deleted)).andExpect(status().isConflict());
    }

    @Test
    void TC_FR2_02_expiryAtOrBeforeCreationOrMalformedIsRejected() throws Exception {
        long before = repository.count();
        // the test clock is fixed at 2030-01-01T00:00:00Z
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "2030-01-01T00:00:00Z")).andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid_expiry"));
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "2029-12-31T23:59:59Z")).andExpect(status().isBadRequest());
        postLink(Map.of("url", "https://example.com/e", "expiresAt", "not-a-timestamp")).andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid_request"));
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_FR2_02_offsetExpiryIsNormalizedToUtc() throws Exception {
        String alias = uniqueAlias("utc");
        create("https://example.com/utc", alias, "2030-01-01T05:30:00+05:00");
        mvc.perform(get("/api/links/" + alias))
                .andExpect(jsonPath("$.expiresAt").value("2030-01-01T00:30:00Z"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"not a url", "http://", "javascript:alert(1)", "ftp://example.com/file", "mailto:a@example.com",
            "//example.com/no-scheme", "file:///etc/passwd"})
    void TC_NFR2_01_malformedOrNonHttpUrlIsRejected(String url) throws Exception {
        long before = repository.count();
        postLink(Map.of("url", url)).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_NFR2_01_urlLengthLimitIs2048() throws Exception {
        String prefix = "https://example.com/";
        String exactly2048 = prefix + "a".repeat(2048 - prefix.length());
        create(exactly2048);
        long before = repository.count();
        postLink(Map.of("url", exactly2048 + "a")).andExpect(status().isBadRequest());
        assertThat(repository.count()).isEqualTo(before);
    }

    @Test
    void TC_NFR2_01_missingUrlOrBodyIsRejected() throws Exception {
        postLink(Map.of("alias", uniqueAlias("nourl"))).andExpect(status().isBadRequest());
        mvc.perform(post("/api/links")
                .contentType("application/json").content("{\"url\":")).andExpect(status().isBadRequest());
    }
}

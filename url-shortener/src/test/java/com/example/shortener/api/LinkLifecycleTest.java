package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.Link;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;

class LinkLifecycleTest extends IntegrationTest {

    private static final String TOKEN = "X-Management-Token";

    // --- FR3 redirect -------------------------------------------------------------------------

    @Test
    void TC_FR3_01_activeLinkRedirectsWith302AndNoStore() throws Exception {
        String url = "https://example.com/tc-fr3-01?q=1&r=two";
        String code = create(url).get("code").asText();
        mvc.perform(get("/" + code))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", url))
                .andExpect(header().string("Cache-Control", containsString("no-store")));
    }

    @Test
    void TC_FR3_02_expiredLinkReturns410WithoutLocation() throws Exception {
        String code = create("https://example.com/tc-fr3-02", null, "2030-01-01T00:00:10Z").get("code").asText();
        clock.advance(Duration.ofSeconds(11));
        mvc.perform(get("/" + code))
                .andExpect(status().isGone())
                .andExpect(header().doesNotExist("Location"))
                .andExpect(jsonPath("$.error").value("expired"));
    }

    @Test
    void TC_FR3_03_unknownAndDeletedCodesReturn404WithoutLocation() throws Exception {
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound()).andExpect(header().doesNotExist("Location"));
        JsonNode created = create("https://example.com/tc-fr3-03");
        String code = created.get("code").asText();
        deleteWith(code, created.get("managementToken").asText()).andExpect(status().isNoContent());
        mvc.perform(get("/" + code)).andExpect(status().isNotFound()).andExpect(header().doesNotExist("Location"));
    }

    // --- FR2 expiry -----------------------------------------------------------------------------

    @Test
    void TC_FR2_01_redirectsBeforeExpiryAnd410AtAndAfterIt() throws Exception {
        Instant expiry = MutableClock.START.plus(Duration.ofMinutes(5));
        String code = create("https://example.com/tc-fr2-01", null, expiry.toString()).get("code").asText();

        clock.set(expiry.minusNanos(1_000)); // one microsecond before
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        clock.set(expiry); // exactly at the instant: expired
        mvc.perform(get("/" + code)).andExpect(status().isGone());
        clock.set(expiry.plus(Duration.ofDays(1)));
        mvc.perform(get("/" + code)).andExpect(status().isGone());
    }

    @Test
    void TC_FR2_03_expiredLinkKeepsPublicMetadata() throws Exception {
        String alias = uniqueAlias("exp");
        create("https://example.com/tc-fr2-03", alias, "2030-01-01T00:01:00Z");
        clock.advance(Duration.ofHours(1));
        mvc.perform(get("/api/links/" + alias))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.originalUrl").value("https://example.com/tc-fr2-03"))
                .andExpect(jsonPath("$.expiresAt").value("2030-01-01T00:01:00Z"));
        assertThat(repository.findByCode(alias)).get().extracting(Link::isDeleted).isEqualTo(false);
    }

    // --- FR4 metadata ---------------------------------------------------------------------------

    @Test
    void TC_FR4_01_publicMetadataWithoutCredentials() throws Exception {
        String code = create("https://example.com/tc-fr4-01").get("code").asText();
        mvc.perform(get("/api/links/" + code))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(code))
                .andExpect(jsonPath("$.alias").value(nullValue()))
                .andExpect(jsonPath("$.originalUrl").value("https://example.com/tc-fr4-01"))
                .andExpect(jsonPath("$.createdAt").value("2030-01-01T00:00:00Z"))
                .andExpect(jsonPath("$.expiresAt").value(nullValue()))
                .andExpect(jsonPath("$.managementToken").doesNotExist());

        String alias = uniqueAlias("meta");
        create("https://example.com/tc-fr4-01b", alias, "2031-06-01T12:00:00Z");
        mvc.perform(get("/api/links/" + alias))
                .andExpect(jsonPath("$.alias").value(alias))
                .andExpect(jsonPath("$.expiresAt").value("2031-06-01T12:00:00Z"));
    }

    @Test
    void TC_FR4_02_metadataForUnknownAndDeletedCodesIs404() throws Exception {
        mvc.perform(get("/api/links/Zz9Zz9Zz")).andExpect(status().isNotFound());
        JsonNode created = create("https://example.com/tc-fr4-02");
        String code = created.get("code").asText();
        deleteWith(code, created.get("managementToken").asText()).andExpect(status().isNoContent());
        mvc.perform(get("/api/links/" + code)).andExpect(status().isNotFound());
    }

    // --- FR5 deletion ---------------------------------------------------------------------------

    @Test
    void TC_FR5_01_authorizedDeletionLeavesTombstoneThatReservesTheCode() throws Exception {
        String alias = uniqueAlias("del");
        JsonNode created = create("https://example.com/tc-fr5-01", alias, null);

        deleteWith(alias, created.get("managementToken").asText())
                .andExpect(status().isNoContent())
                .andExpect(result -> assertThat(result.getResponse().getContentAsString()).isEmpty());

        Link tombstone = repository.findByCode(alias).orElseThrow();
        assertThat(tombstone.isDeleted()).isTrue();
        assertThat(tombstone.getOriginalUrl()).isNull();
        assertThat(tombstone.getTokenHash()).isNull();
        mvc.perform(get("/" + alias)).andExpect(status().isNotFound());
        mvc.perform(get("/api/links/" + alias)).andExpect(status().isNotFound());
        postLink(java.util.Map.of("url", "https://example.com/reuse", "alias", alias)).andExpect(status().isConflict());
    }

    @Test
    void TC_FR5_02_missingTokenIs401AndLinkSurvives() throws Exception {
        String code = create("https://example.com/tc-fr5-02").get("code").asText();
        mvc.perform(delete("/api/links/" + code)).andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("missing_token"));
        mvc.perform(get("/" + code)).andExpect(status().isFound())
                .andExpect(header().string("Location", "https://example.com/tc-fr5-02"));
    }

    @Test
    void TC_FR5_03_invalidTokenIs403AndLinkSurvives() throws Exception {
        JsonNode created = create("https://example.com/tc-fr5-03");
        String code = created.get("code").asText();
        deleteWith(code, "wrong-" + created.get("managementToken").asText()).andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("invalid_token"));
        assertThat(repository.findByCode(code)).get().extracting(Link::isDeleted).isEqualTo(false);
        mvc.perform(get("/" + code)).andExpect(status().isFound());
    }

    @Test
    void TC_FR5_04_deletingUnknownOrAlreadyDeletedCodeIs404() throws Exception {
        deleteWith("Zz9Zz9Zz", "any-token").andExpect(status().isNotFound());
        JsonNode created = create("https://example.com/tc-fr5-04");
        String code = created.get("code").asText();
        String token = created.get("managementToken").asText();
        deleteWith(code, token).andExpect(status().isNoContent());
        deleteWith(code, token).andExpect(status().isNotFound());
    }

    @Test
    void TC_FR5_05_onlyTheTokenHashIsPersistedAndTheTokenIsNeverEchoed() throws Exception {
        JsonNode created = create("https://example.com/tc-fr5-05");
        String code = created.get("code").asText();
        String token = created.get("managementToken").asText();
        assertThat(token).matches("[A-Za-z0-9_-]{43}"); // 256 bits, unpadded base64url

        Link stored = repository.findByCode(code).orElseThrow();
        assertThat(stored.getTokenHash()).isEqualTo(sha256Hex(token)).doesNotContain(token);

        String metadata = mvc.perform(get("/api/links/" + code)).andReturn().getResponse().getContentAsString();
        String redirectHeaders = String.join(";", mvc.perform(get("/" + code)).andReturn().getResponse().getHeaderValues("Location")
                .stream().map(Object::toString).toList());
        assertThat(metadata).doesNotContain(token).doesNotContain(stored.getTokenHash());
        assertThat(redirectHeaders).doesNotContain(token);
    }

    private org.springframework.test.web.servlet.ResultActions deleteWith(String code, String token) throws Exception {
        return mvc.perform(delete("/api/links/" + code).header(TOKEN, token));
    }

    private static String sha256Hex(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}

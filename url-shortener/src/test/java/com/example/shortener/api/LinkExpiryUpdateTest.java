package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.ResultActions;
import org.yaml.snakeyaml.Yaml;

/**
 * PATCH /api/links/{code}: the owner sets or removes a link's expiry. The clock starts at
 * {@link MutableClock#START} (2030-01-01T00:00:00Z) in every test.
 */
class LinkExpiryUpdateTest extends IntegrationTest {

    private static final String TOKEN = "X-Management-Token";
    private static final String IN_ONE_MINUTE = "2030-01-01T00:01:00Z";

    // --- FR1 set, remove, required field ---------------------------------------------------------

    @Test
    void TC_FR1_01_ownerSetsAFutureExpiryAndGetsUpdatedMetadata() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-01", null, IN_ONE_MINUTE);
        String code = link.get("code").asText();
        update(code, token(link), "{\"expiresAt\":\"2031-06-01T12:00:00Z\"}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(code))
                .andExpect(jsonPath("$.originalUrl").value("https://example.com/tc-fr1-01"))
                .andExpect(jsonPath("$.expiresAt").value("2031-06-01T12:00:00Z"))
                .andExpect(jsonPath("$.managementToken").doesNotExist());
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse("2031-06-01T12:00:00Z"));
    }

    @Test
    void TC_FR1_02_explicitNullRemovesTheExpiry() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-02", null, IN_ONE_MINUTE);
        String code = link.get("code").asText();
        update(code, token(link), "{\"expiresAt\":null}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.expiresAt").doesNotExist()); // metadata omits an absent expiry, as before
        assertThat(storedExpiry(code)).isNull();
    }

    @Test
    void TC_FR1_03_omittedExpiresAtIsRejectedAndChangesNothing() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-03", null, IN_ONE_MINUTE);
        String code = link.get("code").asText();
        for (String body : List.of("{}", "{\"expires\":null}")) {
            update(code, token(link), body)
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.error").value("invalid_request"));
        }
        assertThat(storedExpiry(code)).as("an incomplete request never clears the expiry")
                .isEqualTo(Instant.parse(IN_ONE_MINUTE));
    }

    @Test
    void TC_FR1_04_malformedBodiesAndValuesAreRejectedAndChangeNothing() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-04", null, IN_ONE_MINUTE);
        String code = link.get("code").asText();
        for (String body : List.of("{not json", "[]", "null", "{\"expiresAt\":\"tomorrow\"}",
                "{\"expiresAt\":\"2031-13-45T00:00:00Z\"}", "{\"expiresAt\":{}}")) {
            update(code, token(link), body)
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.error").value("invalid_request"));
        }
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse(IN_ONE_MINUTE));
    }

    // --- FR2 only the token holder ------------------------------------------------------------------

    @Test
    void TC_FR2_01_missingTokenIs401AndChangesNothing() throws Exception {
        String code = create("https://example.com/tc-fr2-01", null, IN_ONE_MINUTE).get("code").asText();
        update(code, null, "{\"expiresAt\":null}")
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("missing_token"));
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse(IN_ONE_MINUTE));
    }

    @Test
    void TC_FR2_02_wrongTokenIs403AndChangesNothing() throws Exception {
        JsonNode other = create("https://example.com/tc-fr2-02-other");
        String code = create("https://example.com/tc-fr2-02", null, IN_ONE_MINUTE).get("code").asText();
        update(code, token(other), "{\"expiresAt\":null}") // another link's valid token is still wrong here
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("invalid_token"));
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse(IN_ONE_MINUTE));
    }

    // --- FR3 immediate effect ------------------------------------------------------------------------

    @Test
    void TC_FR3_01_redirectsUseTheNewExpiryImmediately() throws Exception {
        JsonNode shortened = create("https://example.com/tc-fr3-01-a", null, IN_ONE_MINUTE);
        String a = shortened.get("code").asText();
        update(a, token(shortened), "{\"expiresAt\":\"2030-01-01T00:00:30Z\"}").andExpect(status().isOk());
        mvc.perform(get("/api/links/" + a)).andExpect(jsonPath("$.expiresAt").value("2030-01-01T00:00:30Z"));

        JsonNode removed = create("https://example.com/tc-fr3-01-b", null, "2030-01-01T00:00:10Z");
        String b = removed.get("code").asText();
        update(b, token(removed), "{\"expiresAt\":null}").andExpect(status().isOk());

        clock.advance(Duration.ofSeconds(31));
        mvc.perform(get("/" + a)).andExpect(status().isGone()).andExpect(jsonPath("$.error").value("expired"));
        mvc.perform(get("/" + b)).andExpect(status().isFound())
                .andExpect(header().string("Location", "https://example.com/tc-fr3-01-b"));
    }

    // --- FR4 an expired link is never revived ------------------------------------------------------

    @Test
    void TC_FR4_01_anExpiredLinkCannotBeExtendedOrClearedAndStaysExpired() throws Exception {
        JsonNode link = create("https://example.com/tc-fr4-01", null, "2030-01-01T00:00:10Z");
        String code = link.get("code").asText();
        clock.advance(Duration.ofSeconds(10)); // exactly at the expiry instant: expired (FR2 boundary of creation)
        for (String body : List.of("{\"expiresAt\":\"2031-01-01T00:00:00Z\"}", "{\"expiresAt\":null}")) {
            update(code, token(link), body)
                    .andExpect(status().isGone())
                    .andExpect(jsonPath("$.error").value("expired"));
        }
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse("2030-01-01T00:00:10Z"));
        mvc.perform(get("/" + code)).andExpect(status().isGone());
    }

    @Test
    void TC_FR4_01_theTokenIsCheckedBeforeExpiryIsRevealed() throws Exception {
        String code = create("https://example.com/tc-fr4-01-token", null, "2030-01-01T00:00:10Z").get("code").asText();
        clock.advance(Duration.ofSeconds(11));
        update(code, "wrong", "{\"expiresAt\":null}").andExpect(status().isForbidden());
    }

    // --- FR5 past or present values ------------------------------------------------------------------

    @Test
    void TC_FR5_01_anExpiryAtOrBeforeNowIsRejectedAndChangesNothing() throws Exception {
        JsonNode link = create("https://example.com/tc-fr5-01", null, IN_ONE_MINUTE);
        String code = link.get("code").asText();
        for (String value : List.of("2030-01-01T00:00:00Z", "2029-12-31T23:59:59Z", "2030-01-01T00:00:00.0000009Z")) {
            update(code, token(link), "{\"expiresAt\":\"" + value + "\"}")
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.error").value("invalid_expiry"));
        }
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse(IN_ONE_MINUTE));
    }

    // --- FR6 deleted and unknown links -----------------------------------------------------------------

    @Test
    void TC_FR6_01_deletedAndUnknownLinksAre404AndTheTombstoneStays() throws Exception {
        JsonNode link = create("https://example.com/tc-fr6-01");
        String code = link.get("code").asText();
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete("/api/links/" + code)
                .header(TOKEN, token(link))).andExpect(status().isNoContent());
        update(code, token(link), "{\"expiresAt\":\"2031-01-01T00:00:00Z\"}")
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("not_found"));
        update("Zz9Zz9Zz", token(link), "{\"expiresAt\":null}").andExpect(status().isNotFound());
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
        assertThat(storedExpiry(code)).isNull();
    }

    // --- FR7 no maximum ---------------------------------------------------------------------------------

    @Test
    void TC_FR7_01_aFarFutureExpiryIsAcceptedAtStoredPrecision() throws Exception {
        JsonNode link = create("https://example.com/tc-fr7-01");
        String code = link.get("code").asText();
        update(code, token(link), "{\"expiresAt\":\"9999-12-31T23:59:59.999999Z\"}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.expiresAt").value("9999-12-31T23:59:59.999999Z"));
        assertThat(storedExpiry(code)).isEqualTo(Instant.parse("9999-12-31T23:59:59.999999Z"));
    }

    // --- NFR2 the API definition describes the operation -------------------------------------------------

    @Test
    @SuppressWarnings("unchecked")
    void TC_NFR2_01_theApiDefinitionDescribesTheExpiryChange() throws Exception {
        Map<String, Object> spec = new Yaml().load(Files.readString(Path.of("openapi.yaml")));
        assertThat((String) spec.get("openapi")).startsWith("3.");
        Map<String, Object> operation = (Map<String, Object>) ((Map<String, Object>) ((Map<String, Object>)
                spec.get("paths")).get("/api/links/{code}")).get("patch");
        assertThat(operation).as("PATCH /api/links/{code} is documented").isNotNull();
        assertThat(((Map<String, Object>) operation.get("responses")).keySet())
                .contains("200", "400", "401", "403", "404", "410", "429");

        Map<String, Object> components = (Map<String, Object>) spec.get("components");
        Map<String, Object> scheme = (Map<String, Object>) ((Map<String, Object>) components.get("securitySchemes"))
                .get("ManagementToken");
        assertThat(scheme).containsEntry("in", "header").containsEntry("name", TOKEN);
        assertThat(operation.get("security")).isEqualTo(List.of(Map.of("ManagementToken", List.of())));

        Map<String, Object> body = (Map<String, Object>) ((Map<String, Object>) components.get("schemas"))
                .get("UpdateLinkExpiryRequest");
        assertThat((List<String>) body.get("required")).containsExactly("expiresAt");
        assertThat(((Map<String, Object>) ((Map<String, Object>) body.get("properties")).get("expiresAt")))
                .containsEntry("nullable", true).containsEntry("format", "date-time");
    }

    private ResultActions update(String code, String token, String body) throws Exception {
        var request = patch("/api/links/" + code).contentType(MediaType.APPLICATION_JSON).content(body);
        return mvc.perform(token == null ? request : request.header(TOKEN, token));
    }

    private static String token(JsonNode created) {
        return created.get("managementToken").asText();
    }

    private Instant storedExpiry(String code) {
        return repository.findByCode(code).orElseThrow().getExpiresAt();
    }
}

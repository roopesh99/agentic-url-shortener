package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.support.IntegrationTest;
import com.example.shortener.support.MutableClock;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.ResultActions;

/** Click analytics through the running application: counting, the stats contract, privacy, deletion. */
class LinkStatsTest extends IntegrationTest {

    private static final String TOKEN = "X-Management-Token";

    @Autowired
    private ClickEventRepository clicks;

    @Autowired
    private JdbcTemplate jdbc;

    // --- FR1 counting -------------------------------------------------------------------------

    @Test
    void TC_FR1_01_eachSuccessfulRedirectIsOneClickAndTheRedirectIsUnchanged() throws Exception {
        JsonNode link = create("https://example.com/tc-fr1-01");
        String code = link.get("code").asText();
        for (int i = 0; i < 3; i++) {
            mvc.perform(get("/" + code))
                    .andExpect(status().isFound())
                    .andExpect(header().string("Location", "https://example.com/tc-fr1-01"))
                    .andExpect(header().string("Cache-Control", containsString("no-store")));
        }
        stats(code, link).andExpect(status().isOk()).andExpect(jsonPath("$.totalClicks").value(3));
    }

    @Test
    void TC_FR1_02_unknownAndExpiredRedirectsRecordNoClick() throws Exception {
        long before = clicks.count();
        mvc.perform(get("/Zz9Zz9Zz")).andExpect(status().isNotFound());
        JsonNode link = create("https://example.com/tc-fr1-02", null, "2030-01-01T00:00:05Z");
        clock.advance(Duration.ofSeconds(10));
        mvc.perform(get("/" + link.get("code").asText())).andExpect(status().isGone());
        assertThat(clicks.count()).isEqualTo(before);
    }

    // --- FR2 stats contract ----------------------------------------------------------------------

    @Test
    void TC_FR2_01_lifetimeTotalThirtyUtcDaysOldestFirstAndLatestClick() throws Exception {
        JsonNode link = create("https://example.com/tc-fr2-01");
        String code = link.get("code").asText();
        clickAt(code, "2030-01-01T10:00:00Z");                  // outside the window: lifetime total only
        clickAt(code, "2030-01-17T00:00:00Z");                  // first day of the window, at midnight UTC
        clickAt(code, "2030-02-10T23:59:59Z");
        clickAt(code, "2030-02-10T08:00:00Z");
        Instant latest = Instant.parse("2030-02-15T11:59:00Z");
        clickAt(code, latest.toString());
        clock.set(Instant.parse("2030-02-15T12:00:00Z"));       // window: 2030-01-17 .. 2030-02-15

        JsonNode s = json.readTree(stats(code, link).andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertThat(s.get("totalClicks").asLong()).isEqualTo(5);
        JsonNode days = s.get("dailyClicks");
        assertThat(days).hasSize(30);
        assertThat(days.get(0).get("date").asText()).isEqualTo("2030-01-17");
        assertThat(days.get(0).get("clicks").asLong()).isEqualTo(1);
        assertThat(days.get(29).get("date").asText()).isEqualTo("2030-02-15");
        assertThat(days.get(29).get("clicks").asLong()).isEqualTo(1);
        assertThat(dayCount(days, "2030-02-10")).isEqualTo(2);
        assertThat(dayCount(days, "2030-02-11")).isZero();
        for (int i = 1; i < days.size(); i++) {
            assertThat(days.get(i).get("date").asText()).isGreaterThan(days.get(i - 1).get("date").asText());
        }
        assertThat(s.get("lastClickedAt").asText()).isEqualTo(latest.toString());
    }

    @Test
    void TC_FR2_02_linkWithoutClicksHasZeroesAndNullLastClick() throws Exception {
        JsonNode link = create("https://example.com/tc-fr2-02");
        JsonNode s = json.readTree(stats(link.get("code").asText(), link).andReturn().getResponse().getContentAsString());
        assertThat(s.get("totalClicks").asLong()).isZero();
        assertThat(s.get("dailyClicks")).hasSize(30).allSatisfy(d -> assertThat(d.get("clicks").asLong()).isZero());
        assertThat(s.get("dailyClicks").get(29).get("date").asText()).isEqualTo("2030-01-01");
        assertThat(s.get("lastClickedAt").isNull()).isTrue();
    }

    @Test
    void TC_FR2_03_missingOrBlankTokenIs401() throws Exception {
        String code = create("https://example.com/tc-fr2-03").get("code").asText();
        mvc.perform(get("/api/links/" + code + "/stats")).andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("missing_token"));
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, "  ")).andExpect(status().isUnauthorized());
    }

    @Test
    void TC_FR2_04_wrongTokenIs403AndRevealsNoStats() throws Exception {
        String code = create("https://example.com/tc-fr2-04").get("code").asText();
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, "not-the-token"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("invalid_token"))
                .andExpect(jsonPath("$.totalClicks").doesNotExist());
    }

    @Test
    void TC_FR2_05_unknownCodeIs404() throws Exception {
        mvc.perform(get("/api/links/Zz9Zz9Zz/stats").header(TOKEN, "anything"))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.totalClicks").doesNotExist());
    }

    // --- FR3 expiry and deletion -----------------------------------------------------------------

    @Test
    void TC_FR3_01_expiredLinkStillHasStats() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-01", null, "2030-01-01T01:00:00Z");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        clock.advance(Duration.ofHours(2));
        stats(code, link).andExpect(status().isOk()).andExpect(jsonPath("$.totalClicks").value(1));
    }

    @Test
    void TC_FR3_02_deletionErasesEveryClickAndKeepsTheTombstone() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-02");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code));
        mvc.perform(get("/" + code));
        Long linkId = repository.findByCode(code).orElseThrow().getId();
        assertThat(clicks.countByLinkId(linkId)).isEqualTo(2);

        mvc.perform(delete("/api/links/" + code).header(TOKEN, link.get("managementToken").asText()))
                .andExpect(status().isNoContent());
        assertThat(clicks.countByLinkId(linkId)).isZero();
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
    }

    @Test
    void TC_FR3_04_deletedLinkHasNoStats() throws Exception {
        JsonNode link = create("https://example.com/tc-fr3-04");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();
        mvc.perform(delete("/api/links/" + code).header(TOKEN, token)).andExpect(status().isNoContent());
        mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, token)).andExpect(status().isNotFound());
    }

    // --- FR5 / NFR2 privacy ----------------------------------------------------------------------

    @Test
    void TC_FR5_01_statsReportClickCountsOnly() throws Exception {
        JsonNode link = create("https://example.com/tc-fr5-01");
        mvc.perform(get("/" + link.get("code").asText()));
        JsonNode s = json.readTree(stats(link.get("code").asText(), link).andReturn().getResponse().getContentAsString());
        assertThat(fieldNames(s)).containsExactlyInAnyOrder("totalClicks", "dailyClicks", "lastClickedAt");
        assertThat(fieldNames(s.get("dailyClicks").get(0))).containsExactlyInAnyOrder("date", "clicks");
    }

    @Test
    void TC_NFR2_01_noVisitorDataIsStoredEvenWhenTheRequestCarriesIt() throws Exception {
        JsonNode link = create("https://example.com/tc-nfr2-01");
        String code = link.get("code").asText();
        mvc.perform(get("/" + code).with(request -> {
            request.setRemoteAddr("203.0.113.77");
            return request;
        }).header("User-Agent", "Mozilla/5.0 PrivacyProbe").header("X-Forwarded-For", "198.51.100.23")
                .header("Cookie", "visitor=probe-cookie-123").header("Referer", "https://referrer.example/probe"))
                .andExpect(status().isFound());

        List<String> columns = jdbc.queryForList(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'CLICK_EVENTS'", String.class);
        assertThat(columns).containsExactlyInAnyOrder("ID", "LINK_ID", "CLICKED_AT", "CLICK_DATE");

        Long linkId = repository.findByCode(code).orElseThrow().getId();
        String stored = jdbc.queryForList("SELECT * FROM click_events WHERE link_id = ?", linkId).toString();
        for (String probe : List.of("203.0.113.77", "198.51.100.23", "PrivacyProbe", "probe-cookie-123", "referrer.example")) {
            assertThat(stored).doesNotContain(probe);
        }
    }

    private ResultActions stats(String code, JsonNode created) throws Exception {
        return mvc.perform(get("/api/links/" + code + "/stats").header(TOKEN, created.get("managementToken").asText()));
    }

    private void clickAt(String code, String instant) throws Exception {
        clock.set(Instant.parse(instant));
        mvc.perform(get("/" + code)).andExpect(status().isFound());
    }

    private static long dayCount(JsonNode days, String date) {
        for (JsonNode d : days) {
            if (d.get("date").asText().equals(date)) {
                return d.get("clicks").asLong();
            }
        }
        throw new AssertionError("no entry for " + date);
    }

    private static Set<String> fieldNames(JsonNode node) {
        Set<String> names = new HashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }
}

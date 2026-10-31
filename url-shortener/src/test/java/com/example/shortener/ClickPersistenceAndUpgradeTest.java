package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;

import com.example.shortener.api.HealthController;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.TestSupportConfig;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** NFR3 and NFR4: click data survives restarts, and an existing V1 database upgrades in place. */
class ClickPersistenceAndUpgradeTest {

    @TempDir
    Path dataDir;

    @Test
    void TC_NFR3_01_clicksSurviveARestart() {
        String code;
        String token;
        try (ConfigurableApplicationContext first = start()) {
            var created = first.getBean(LinkService.class).create("https://example.com/persist", null, null);
            code = created.link().getCode();
            token = created.managementToken();
            Long id = created.link().getId();
            first.getBean(ClickRecorder.class).record(id);
            first.getBean(ClickRecorder.class).record(id);
        }
        try (ConfigurableApplicationContext second = start()) {
            assertThat(second.getBean(LinkService.class).stats(code, token).totalClicks()).isEqualTo(2);
        }
    }

    /** An existing deployment: a database migrated to V1 only, holding a link and a tombstone. */
    @Test
    void TC_NFR4_01_existingV1DatabaseUpgradesWithoutTouchingItsData() {
        String url = "jdbc:h2:file:" + dataDir.toAbsolutePath() + "/shortener;DB_CLOSE_ON_EXIT=FALSE";
        Flyway.configure().dataSource(url, "sa", "").locations("classpath:db/migration").target("1").load().migrate();
        JdbcTemplate v1 = new JdbcTemplate(new DriverManagerDataSource(url, "sa", ""));
        v1.update("INSERT INTO links (code, original_url, custom_alias, created_at, token_hash) VALUES "
                + "('old-link', 'https://example.com/old', TRUE, CURRENT_TIMESTAMP, ?)", "a".repeat(64));
        v1.update("INSERT INTO links (code, original_url, custom_alias, created_at, token_hash, deleted_at) VALUES "
                + "('old-tomb', NULL, TRUE, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)");

        try (ConfigurableApplicationContext app = start()) {
            Flyway flyway = app.getBean(Flyway.class);
            assertThat(flyway.info().applied()).extracting(m -> m.getVersion().getVersion()).containsExactly("1", "2");
            assertThat(flyway.validateWithResult().validationSuccessful).as("V1 checksum unchanged").isTrue();

            LinkService links = app.getBean(LinkService.class);
            assertThat(links.resolveForRedirect("old-link")).isEqualTo("https://example.com/old");
            Long oldId = links.metadata("old-link").getId();
            app.getBean(ClickRecorder.class).record(oldId);
            assertThat(app.getBean(JdbcTemplate.class).queryForObject(
                    "SELECT COUNT(*) FROM click_events WHERE link_id = ?", Long.class, oldId)).isEqualTo(1);
            assertThat(app.getBean(HealthController.class).health().getStatusCode()).isEqualTo(HttpStatus.OK);
        }
    }

    private ConfigurableApplicationContext start() {
        // Command-line args, not builder.properties(): those are defaults that application.yml overrides.
        return new SpringApplicationBuilder(ShortenerApplication.class, TestSupportConfig.class)
                .run("--shortener.data-dir=" + dataDir.toAbsolutePath(), "--server.port=0");
    }
}

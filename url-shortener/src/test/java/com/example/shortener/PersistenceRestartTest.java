package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.file.Files;
import java.nio.file.Path;

import com.example.shortener.api.HealthController;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.RateLimitedException;
import com.example.shortener.support.TestSupportConfig;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.HttpStatus;

/**
 * NFR4: the real application, started twice on the same file-based H2 store under a temporary
 * data directory, as a restart would. Uses the production configuration apart from the data
 * directory, a random port, and stubbed DNS/clock.
 */
class PersistenceRestartTest {

    @TempDir
    Path dataDir;

    @Test
    void TC_NFR4_01_linksAndTombstonesSurviveRestartAndMigrationsAreApplied() {
        String activeCode;
        String tombstoneAlias = "kept-forever";
        try (ConfigurableApplicationContext first = start()) {
            LinkService links = first.getBean(LinkService.class);
            activeCode = links.create("https://example.com/persisted", null, null).link().getCode();
            var doomed = links.create("https://example.com/doomed", tombstoneAlias, null);
            links.delete(tombstoneAlias, doomed.managementToken());

            CreateRateLimiter limiter = first.getBean(CreateRateLimiter.class);
            for (int i = 0; i < 20; i++) {
                limiter.acquire("192.0.2.10");
            }
            assertThatThrownBy(() -> limiter.acquire("192.0.2.10")).isInstanceOf(RateLimitedException.class);
        }

        assertThat(Files.exists(dataDir.resolve("shortener.mv.db"))).as("file-based H2 under the data dir").isTrue();

        try (ConfigurableApplicationContext second = start()) {
            LinkService links = second.getBean(LinkService.class);
            assertThat(links.resolveForRedirect(activeCode)).isEqualTo("https://example.com/persisted");
            assertThatThrownBy(() -> links.resolveForRedirect(tombstoneAlias))
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.NOT_FOUND));
            assertThatThrownBy(() -> links.create("https://example.com/reuse", tombstoneAlias, null))
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.CONFLICT));

            assertThat(second.getBean(Flyway.class).info().applied()).extracting(m -> m.getVersion().getVersion())
                    .containsExactly("1");
            second.getBean(CreateRateLimiter.class).acquire("192.0.2.10"); // in-memory limit reset by the restart
        }
    }

    /** TC-NFR4-02: starts from a clean directory with no external infrastructure and reports healthy. */
    @Test
    void TC_NFR4_02_startsLocallyAndReportsHealthy() {
        try (ConfigurableApplicationContext app = start()) {
            assertThat(app.getBean(HealthController.class).health().getStatusCode()).isEqualTo(HttpStatus.OK);
            assertThat(app.getBean(Flyway.class).info().current().getVersion().getVersion()).isEqualTo("1");
        }
    }

    private ConfigurableApplicationContext start() {
        // Command-line args, not builder.properties(): those are defaults that application.yml overrides.
        return new SpringApplicationBuilder(ShortenerApplication.class, TestSupportConfig.class)
                .run("--shortener.data-dir=" + dataDir.toAbsolutePath(), "--server.port=0");
    }
}

package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.fail;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * TC-FR3-03: a click being recorded and the link being deleted at the same moment. Each test
 * forces one interleaving by holding the first operation's transaction open (and so its row lock)
 * while the second starts; either way no click may survive the deletion. The expiry-change tests
 * do the same for an expiry change against click recording and against deletion.
 *
 * <p>Each race proves its interleaving: the first operation's transaction is released only after
 * H2 reports the second operation's session BLOCKED by the first one's session, on a row-lock query
 * for the same link ({@code INFORMATION_SCHEMA.SESSIONS}, with the statement's bound parameter). If
 * that is not observed within a bound, or the second operation finishes without waiting, the test
 * fails, and the first transaction is rolled back rather than committed as if the race had happened.
 */
class ClickDeletionRaceTest extends IntegrationTest {

    /** How long any one step may take before the test fails with a diagnostic instead of hanging. */
    private static final Duration BOUND = Duration.ofSeconds(5);

    @Autowired
    private ClickRecorder recorder;

    @Autowired
    private LinkService links;

    @Autowired
    private ClickEventRepository clicks;

    @Autowired
    private TransactionTemplate tx;

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void TC_FR3_03_clickInFlightWhenDeleteArrivesIsErasedByTheDelete() throws Exception {
        JsonNode link = create("https://example.com/race-1");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();

        race(() -> recorder.record(id),                                   // takes the row lock, inserts
             () -> run(() -> links.delete(code, link.get("managementToken").asText())), byCode(code));

        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
        assertThat(clicks.countByLinkId(id)).as("the delete waited for the click, then erased it").isZero();
    }

    @Test
    void TC_FR3_03_clickArrivingDuringDeleteIsNotRecordedAfterIt() throws Exception {
        JsonNode link = create("https://example.com/race-2");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();

        race(() -> links.delete(code, link.get("managementToken").asText()), // locks, erases, tombstones
             () -> run(() -> recorder.record(id)), byId(id));

        assertThat(clicks.countByLinkId(id)).as("the click waited, then saw the tombstone and recorded nothing").isZero();
    }

    // --- expiry changes on the same row lock --------------------------------------------------

    private static final Instant NEW_EXPIRY = Instant.parse("2031-01-01T00:00:00Z");

    @Test
    void TC_FR3_02_expiryChangeWaitsForAClickInFlightAndBothPersist() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-1", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();

        race(() -> recorder.record(id),
             () -> links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY), byCode(code));

        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isEqualTo(NEW_EXPIRY);
        assertThat(clicks.countByLinkId(id)).isEqualTo(1);
    }

    @Test
    void TC_FR3_02_redirectDuringAnExpiryChangeIsServedAndItsClickIsRecorded() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-2", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();

        // the redirect's lookup does not lock; its click recording waits for the expiry change's lock
        int redirect = race(() -> links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY),
                () -> mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/" + code))
                        .andReturn().getResponse().getStatus(),
                byId(id));

        assertThat(redirect).as("the redirect is served while the update holds the row lock").isEqualTo(302);
        assertThat(clicks.countByLinkId(id)).as("its click waited for the lock, then was recorded").isEqualTo(1);
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isEqualTo(NEW_EXPIRY);
    }

    @Test
    void TC_FR3_03_expiryChangeArrivingDuringDeleteFindsTheTombstone() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-3", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();

        Object updated = race(() -> links.delete(code, token), () -> {
            try {
                return links.updateExpiry(code, token, NEW_EXPIRY);
            } catch (ApiException e) {
                return e.getStatus();
            }
        }, byCode(code));

        assertThat(updated).as("the update waited, then saw the tombstone").isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
    }

    @Test
    void TC_FR3_03_deleteArrivingDuringAnExpiryChangeStillDeletes() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-4", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();

        race(() -> links.updateExpiry(code, token, NEW_EXPIRY), () -> run(() -> links.delete(code, token)), byCode(code));

        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).as("the delete waited, then won").isTrue();
    }

    // --- the proof itself can fail -------------------------------------------------------------

    @Test
    void TC_FR3_01_aSecondOperationThatNeverWaitsFailsTheRaceAndTheFirstIsRolledBack() throws Exception {
        JsonNode link = create("https://example.com/race-guard-1", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();

        assertThatThrownBy(() -> race(() -> links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY),
                                      () -> "finished without touching the link", byCode(code)))
                .isInstanceOf(AssertionError.class)
                .hasMessageContaining("completed without waiting");
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt())
                .as("an unproven interleaving is rolled back, never committed")
                .isEqualTo(Instant.parse("2030-01-01T00:01:00Z"));
    }

    @Test
    void TC_FR3_02_anUnobservedWaitFailsWithinTheBoundWithADiagnostic() throws Exception {
        JsonNode link = create("https://example.com/race-guard-2", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        CountDownLatch never = new CountDownLatch(1);
        long started = System.nanoTime();
        try {
            assertThatThrownBy(() -> race(() -> links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY),
                                          () -> never.await(BOUND.toMillis(), TimeUnit.MILLISECONDS), byCode(code),
                                          Duration.ofMillis(300)))
                    .isInstanceOf(AssertionError.class)
                    .hasMessageContaining("not observed within 300 ms")
                    .hasMessageContaining(byCode(code))
                    .hasMessageContaining("holder session")
                    .hasMessageContaining("second operation done: false");
        } finally {
            never.countDown();
        }
        assertThat(Duration.ofNanos(System.nanoTime() - started)).as("bounded, not hanging").isLessThan(BOUND);
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isEqualTo(Instant.parse("2030-01-01T00:01:00Z"));
    }

    @Test
    void TC_FR2_01_aWaitOnAnotherLinkOrBehindAnotherHolderDoesNotCount() throws Exception {
        JsonNode a = create("https://example.com/race-guard-a");
        JsonNode b = create("https://example.com/race-guard-b");
        String codeA = a.get("code").asText();
        String codeB = b.get("code").asText();
        Long idB = repository.findByCode(codeB).orElseThrow().getId();

        // a second transaction holds link B; the operation under test waits on B, not on A
        Holder other = new Holder(() -> recorder.record(idB));
        try {
            assertThatThrownBy(() -> race(() -> recorder.record(repository.findByCode(codeA).orElseThrow().getId()),
                                          () -> run(() -> links.delete(codeB, b.get("managementToken").asText())),
                                          byCode(codeA), Duration.ofMillis(300)))
                    .isInstanceOf(AssertionError.class)
                    .hasMessageContaining("not observed within 300 ms");
        } finally {
            other.verified.set(true);
            other.close();
        }
    }

    // --- harness -------------------------------------------------------------------------------

    /** The bound statement parameter H2 shows for a row-lock query on a link by code or by id. */
    private static String byCode(String code) {
        return "{1: '" + code + "'}";
    }

    private static String byId(Long id) {
        return "{1: CAST(" + id + " AS BIGINT)}";
    }

    private <T> T race(Runnable first, Callable<T> second, String lockedLink) throws Exception {
        return race(first, second, lockedLink, BOUND);
    }

    /**
     * Runs {@code first} in a transaction that keeps its row lock, starts {@code second}, and lets
     * the first commit only once H2 shows the second blocked by it on {@code lockedLink}'s row.
     */
    private <T> T race(Runnable first, Callable<T> second, String lockedLink, Duration observeFor) throws Exception {
        try (Holder holder = new Holder(first)) {
            CompletableFuture<T> waiting = CompletableFuture.supplyAsync(() -> {
                try {
                    return second.call();
                } catch (Exception e) {
                    throw new CompletionException(e);
                }
            });
            awaitBlocked(holder, waiting, lockedLink, observeFor);
            holder.verified.set(true);
            holder.close();
            holder.done.get(BOUND.toMillis(), TimeUnit.MILLISECONDS);
            try {
                return waiting.get(BOUND.toMillis(), TimeUnit.MILLISECONDS);
            } catch (ExecutionException e) {
                throw e.getCause() instanceof Exception cause ? cause : e;
            }
        }
    }

    private void awaitBlocked(Holder holder, CompletableFuture<?> second, String lockedLink, Duration bound)
            throws InterruptedException {
        long deadline = System.nanoTime() + bound.toNanos();
        List<Map<String, Object>> sessions = List.of(); // the last non-empty observation, for diagnostics
        while (System.nanoTime() < deadline) {
            List<Map<String, Object>> now = jdbc.queryForList("SELECT SESSION_ID, BLOCKER_ID, SESSION_STATE, EXECUTING_STATEMENT "
                    + "FROM INFORMATION_SCHEMA.SESSIONS WHERE BLOCKER_ID IS NOT NULL");
            sessions = now.isEmpty() ? sessions : now;
            boolean waitingOnTheLink = now.stream().anyMatch(s ->
                    ((Number) s.get("BLOCKER_ID")).intValue() == holder.session.get()
                            && "BLOCKED".equals(s.get("SESSION_STATE"))
                            && isRowLockOn(String.valueOf(s.get("EXECUTING_STATEMENT")), lockedLink));
            if (waitingOnTheLink) {
                return;
            }
            if (second.isDone()) {
                fail("the second operation completed without waiting on the row lock of " + lockedLink
                        + " held by session " + holder.session.get() + ": " + second + "; blocked sessions last seen: "
                        + sessions);
            }
            Thread.sleep(2); // polling interval only: the proof is the observation, not the time
        }
        fail("lock wait on " + lockedLink + " not observed within " + bound.toMillis() + " ms; holder session "
                + holder.session.get() + ", second operation done: " + second.isDone() + ", blocked sessions: "
                + sessions);
    }

    private static boolean isRowLockOn(String statement, String lockedLink) {
        String sql = statement.toLowerCase();
        return sql.contains(" from links ") && sql.contains(" for update") && statement.endsWith(lockedLink);
    }

    /** The first operation, in a transaction that keeps its row lock until released. */
    private final class Holder implements AutoCloseable {

        final CountDownLatch locked = new CountDownLatch(1);
        final CountDownLatch release = new CountDownLatch(1);
        final AtomicInteger session = new AtomicInteger(-1);
        final AtomicBoolean verified = new AtomicBoolean();
        final CompletableFuture<Void> done;

        Holder(Runnable first) throws InterruptedException {
            done = CompletableFuture.runAsync(() -> tx.executeWithoutResult(status -> {
                first.run();
                session.set(jdbc.queryForObject("SELECT SESSION_ID()", Integer.class)); // same connection as the lock
                locked.countDown();
                try {
                    release.await(BOUND.toMillis() * 2, TimeUnit.MILLISECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                if (!verified.get()) {
                    status.setRollbackOnly(); // an interleaving that was not proven is never committed
                }
            }));
            if (!locked.await(BOUND.toMillis(), TimeUnit.MILLISECONDS)) {
                release.countDown();
                fail("the first operation did not take its lock within " + BOUND.toMillis() + " ms: " + done);
            }
        }

        /** Lets the first transaction finish (commit if verified, else roll back) and waits for it. */
        @Override
        public void close() {
            release.countDown();
            try {
                done.get(BOUND.toMillis(), TimeUnit.MILLISECONDS);
            } catch (Exception e) {
                // the test is already failing or finishing; the transaction has ended either way
            }
        }
    }

    private static Void run(Runnable operation) {
        operation.run();
        return null;
    }
}

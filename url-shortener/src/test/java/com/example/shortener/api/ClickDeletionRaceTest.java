package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * TC-FR3-03: a click being recorded and the link being deleted at the same moment. Each test
 * forces one interleaving by holding the first operation's transaction open (and so its row lock)
 * while the second starts; either way no click may survive the deletion. The expiry-change tests
 * do the same for an expiry change against click recording and against deletion.
 */
class ClickDeletionRaceTest extends IntegrationTest {

    @Autowired
    private ClickRecorder recorder;

    @Autowired
    private LinkService links;

    @Autowired
    private ClickEventRepository clicks;

    @Autowired
    private TransactionTemplate tx;

    @Test
    void TC_FR3_03_clickInFlightWhenDeleteArrivesIsErasedByTheDelete() throws Exception {
        JsonNode link = create("https://example.com/race-1");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch recordingHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> recording = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            recorder.record(id);            // joins this transaction: takes the row lock, inserts
            recordingHoldsLock.countDown();
            sleep(300);                     // keep the lock while the delete starts
        }));
        assertThat(recordingHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> deleting = CompletableFuture.runAsync(
                () -> links.delete(code, link.get("managementToken").asText()));

        CompletableFuture.allOf(recording, deleting).get(10, TimeUnit.SECONDS);
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
        assertThat(clicks.countByLinkId(id)).as("the delete waited for the click, then erased it").isZero();
    }

    @Test
    void TC_FR3_03_clickArrivingDuringDeleteIsNotRecordedAfterIt() throws Exception {
        JsonNode link = create("https://example.com/race-2");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch deleteHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> deleting = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            links.delete(code, link.get("managementToken").asText());  // takes the row lock, erases, tombstones
            deleteHoldsLock.countDown();
            sleep(300);                                                // commit only after the click starts
        }));
        assertThat(deleteHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> recording = CompletableFuture.runAsync(() -> recorder.record(id));

        CompletableFuture.allOf(recording, deleting).get(10, TimeUnit.SECONDS);
        assertThat(clicks.countByLinkId(id)).as("the click waited, then saw the tombstone and recorded nothing").isZero();
    }

    // --- expiry changes on the same row lock --------------------------------------------------

    private static final Instant NEW_EXPIRY = Instant.parse("2031-01-01T00:00:00Z");

    @Test
    void TC_FR3_02_expiryChangeWaitsForAClickInFlightAndBothPersist() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-1", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch recordingHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> recording = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            recorder.record(id);
            recordingHoldsLock.countDown();
            sleep(300);
        }));
        assertThat(recordingHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> updating = CompletableFuture.runAsync(
                () -> links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY));

        CompletableFuture.allOf(recording, updating).get(10, TimeUnit.SECONDS);
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isEqualTo(NEW_EXPIRY);
        assertThat(clicks.countByLinkId(id)).isEqualTo(1);
    }

    @Test
    void TC_FR3_02_redirectDuringAnExpiryChangeIsServedAndItsClickIsRecorded() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-2", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        Long id = repository.findByCode(code).orElseThrow().getId();
        CountDownLatch updateHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> updating = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            links.updateExpiry(code, link.get("managementToken").asText(), NEW_EXPIRY);
            updateHoldsLock.countDown();
            sleep(300);
        }));
        assertThat(updateHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        int redirect = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/" + code))
                .andReturn().getResponse().getStatus();

        updating.get(10, TimeUnit.SECONDS);
        assertThat(redirect).as("the redirect is served while the update holds the row lock").isEqualTo(302);
        assertThat(clicks.countByLinkId(id)).as("its click waited for the lock, then was recorded").isEqualTo(1);
        assertThat(repository.findByCode(code).orElseThrow().getExpiresAt()).isEqualTo(NEW_EXPIRY);
    }

    @Test
    void TC_FR3_03_expiryChangeArrivingDuringDeleteFindsTheTombstone() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-3", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();
        CountDownLatch deleteHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> deleting = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            links.delete(code, token);
            deleteHoldsLock.countDown();
            sleep(300);
        }));
        assertThat(deleteHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Object> updating = CompletableFuture.supplyAsync(() -> {
            try {
                return links.updateExpiry(code, token, NEW_EXPIRY);
            } catch (ApiException e) {
                return e.getStatus();
            }
        });

        deleting.get(10, TimeUnit.SECONDS);
        assertThat(updating.get(10, TimeUnit.SECONDS)).as("the update waited, then saw the tombstone")
                .isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).isTrue();
    }

    @Test
    void TC_FR3_03_deleteArrivingDuringAnExpiryChangeStillDeletes() throws Exception {
        JsonNode link = create("https://example.com/race-expiry-4", null, "2030-01-01T00:01:00Z");
        String code = link.get("code").asText();
        String token = link.get("managementToken").asText();
        CountDownLatch updateHoldsLock = new CountDownLatch(1);

        CompletableFuture<Void> updating = CompletableFuture.runAsync(() -> tx.executeWithoutResult(s -> {
            links.updateExpiry(code, token, NEW_EXPIRY);
            updateHoldsLock.countDown();
            sleep(300);
        }));
        assertThat(updateHoldsLock.await(5, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> deleting = CompletableFuture.runAsync(() -> links.delete(code, token));

        CompletableFuture.allOf(updating, deleting).get(10, TimeUnit.SECONDS);
        assertThat(repository.findByCode(code).orElseThrow().isDeleted()).as("the delete waited, then won").isTrue();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}

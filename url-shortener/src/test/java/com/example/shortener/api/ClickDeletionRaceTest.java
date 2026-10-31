package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.JsonNode;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * TC-FR3-03: a click being recorded and the link being deleted at the same moment. Each test
 * forces one interleaving by holding the first operation's transaction open (and so its row lock)
 * while the second starts; either way no click may survive the deletion.
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

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}

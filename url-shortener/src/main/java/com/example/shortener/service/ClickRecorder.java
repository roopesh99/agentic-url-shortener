package com.example.shortener.service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;

import com.example.shortener.domain.ClickEvent;
import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.domain.LinkRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Records a click in its own short transaction, separate from the redirect lookup, so the
 * caller can contain any failure (NFR1). The link row is locked while recording, the same lock
 * deletion takes, so a click is never committed after its link's clicks were erased (FR3).
 */
@Service
public class ClickRecorder {

    private final LinkRepository links;
    private final ClickEventRepository clicks;
    private final Clock clock;

    public ClickRecorder(LinkRepository links, ClickEventRepository clicks, Clock clock) {
        this.links = links;
        this.clicks = clicks;
        this.clock = clock;
    }

    @Transactional
    public void record(Long linkId) {
        links.lockById(linkId).filter(link -> !link.isDeleted()).ifPresent(link -> {
            Instant now = clock.instant().truncatedTo(ChronoUnit.MICROS);
            clicks.save(new ClickEvent(linkId, now, LocalDate.ofInstant(now, ZoneOffset.UTC)));
        });
    }
}

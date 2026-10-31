package com.example.shortener.domain;

import java.time.Instant;
import java.time.LocalDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One successful redirect. Deliberately holds no visitor data (no IP address, user agent,
 * cookie or fingerprint): only which link, when, and the UTC day used for daily counts.
 */
@Entity
@Table(name = "click_events")
public class ClickEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "link_id", nullable = false)
    private Long linkId;

    @Column(name = "clicked_at", nullable = false)
    private Instant clickedAt;

    /** Stored, not derived at query time, so daily grouping never depends on a session time zone. */
    @Column(name = "click_date", nullable = false)
    private LocalDate clickDate;

    protected ClickEvent() {
    }

    public ClickEvent(Long linkId, Instant clickedAt, LocalDate clickDate) {
        this.linkId = linkId;
        this.clickedAt = clickedAt;
        this.clickDate = clickDate;
    }

    public Long getLinkId() {
        return linkId;
    }

    public Instant getClickedAt() {
        return clickedAt;
    }

    public LocalDate getClickDate() {
        return clickDate;
    }
}

package com.example.shortener.domain;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A short link. Deletion turns it into a tombstone: the row stays so its code is reserved
 * forever, while the destination URL and token hash are erased.
 */
@Entity
@Table(name = "links")
public class Link {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 32)
    private String code;

    @Column(name = "original_url", length = 2048)
    private String originalUrl;

    @Column(name = "custom_alias", nullable = false)
    private boolean customAlias;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at")
    private Instant expiresAt;

    @Column(name = "token_hash", length = 64)
    private String tokenHash;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    protected Link() {
    }

    public Link(String code, String originalUrl, boolean customAlias, Instant createdAt, Instant expiresAt,
                String tokenHash) {
        this.code = code;
        this.originalUrl = originalUrl;
        this.customAlias = customAlias;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
        this.tokenHash = tokenHash;
    }

    public boolean isDeleted() {
        return deletedAt != null;
    }

    /** Expired at or after the expiry instant (FR2). */
    public boolean isExpiredAt(Instant now) {
        return expiresAt != null && !now.isBefore(expiresAt);
    }

    public void markDeleted(Instant now) {
        this.deletedAt = now;
        this.originalUrl = null;
        this.tokenHash = null;
    }

    public Long getId() {
        return id;
    }

    public String getCode() {
        return code;
    }

    public String getOriginalUrl() {
        return originalUrl;
    }

    public boolean isCustomAlias() {
        return customAlias;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public String getTokenHash() {
        return tokenHash;
    }
}

package com.example.shortener.api;

import java.time.Instant;

import com.example.shortener.domain.Link;

/** Request and response bodies of the /api/links resource. */
public final class LinkDtos {

    private LinkDtos() {
    }

    /** {@code alias} and {@code expiresAt} (ISO-8601 instant) are optional. */
    public record CreateLinkRequest(String url, String alias, Instant expiresAt) {
    }

    public record CreateLinkResponse(String code, String shortPath, String managementToken) {
    }

    /** Public metadata. {@code alias} is set only for links created with a custom alias. */
    public record LinkMetadata(String code, String alias, String originalUrl, Instant createdAt, Instant expiresAt) {

        static LinkMetadata of(Link link) {
            return new LinkMetadata(link.getCode(), link.isCustomAlias() ? link.getCode() : null,
                    link.getOriginalUrl(), link.getCreatedAt(), link.getExpiresAt());
        }
    }

    public record ErrorResponse(String error, String message) {
    }
}

package com.example.shortener.api;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import com.example.shortener.domain.Link;
import com.example.shortener.service.ApiException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.service.LinkService.LinkStats;

/** Request and response bodies of the /api/links resource. */
public final class LinkDtos {

    private LinkDtos() {
    }

    /** {@code alias} and {@code expiresAt} (ISO-8601 instant) are optional. */
    public record CreateLinkRequest(String url, String alias, Instant expiresAt) {
    }

    /**
     * PATCH body. {@code expiresAt} must be present: an instant sets the expiry, an explicit null
     * removes it. A missing field is rejected rather than read as "remove", so an incomplete request
     * can never clear an expiry by accident.
     */
    public record UpdateExpiryRequest(Instant expiresAt) {

        static UpdateExpiryRequest from(JsonNode body, ObjectMapper json) {
            if (body == null || !body.isObject()) {
                throw ApiException.badRequest("invalid_request", "request body must be a JSON object");
            }
            JsonNode value = body.get("expiresAt");
            if (value == null) {
                throw ApiException.badRequest("invalid_request", "expiresAt is required; use null to remove the expiry");
            }
            if (value.isNull()) {
                return new UpdateExpiryRequest(null);
            }
            try {
                // the application's mapper, so an instant parses exactly as it does at creation
                return new UpdateExpiryRequest(json.convertValue(value, Instant.class));
            } catch (IllegalArgumentException e) {
                throw ApiException.badRequest("invalid_request", "request body is not valid JSON for this endpoint");
            }
        }
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

    /** Click counts only: no unique-visitor or other per-visitor metric (FR5). */
    public record StatsResponse(long totalClicks, List<DailyClicksResponse> dailyClicks, Instant lastClickedAt) {

        static StatsResponse of(LinkStats stats) {
            return new StatsResponse(stats.totalClicks(),
                    stats.dailyClicks().stream().map(d -> new DailyClicksResponse(d.date(), d.clicks())).toList(),
                    stats.lastClickedAt());
        }
    }

    public record DailyClicksResponse(LocalDate date, long clicks) {
    }

    public record ErrorResponse(String error, String message) {
    }
}

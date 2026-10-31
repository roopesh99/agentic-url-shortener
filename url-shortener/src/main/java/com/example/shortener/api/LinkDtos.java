package com.example.shortener.api;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import com.example.shortener.domain.Link;
import com.example.shortener.service.LinkService.LinkStats;

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

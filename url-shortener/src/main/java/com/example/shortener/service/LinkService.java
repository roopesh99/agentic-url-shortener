package com.example.shortener.service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import com.example.shortener.domain.ClickEventRepository;
import com.example.shortener.domain.ClickEventRepository.DailyCount;
import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Link lifecycle: create, resolve for redirect, read metadata and stats, change expiry, delete into a tombstone. */
@Service
public class LinkService {

    static final int MAX_CODE_ATTEMPTS = 10;
    static final int STATS_DAYS = 30;

    private final LinkRepository repository;
    private final DestinationPolicy destinationPolicy;
    private final AliasPolicy aliasPolicy;
    private final CodeGenerator codeGenerator;
    private final TokenService tokenService;
    private final ClickEventRepository clicks;
    private final Clock clock;

    public LinkService(LinkRepository repository, DestinationPolicy destinationPolicy, AliasPolicy aliasPolicy,
                       CodeGenerator codeGenerator, TokenService tokenService, ClickEventRepository clicks,
                       Clock clock) {
        this.repository = repository;
        this.destinationPolicy = destinationPolicy;
        this.aliasPolicy = aliasPolicy;
        this.codeGenerator = codeGenerator;
        this.tokenService = tokenService;
        this.clicks = clicks;
        this.clock = clock;
    }

    /** The plaintext management token is returned here and nowhere else. */
    public record CreatedLink(Link link, String managementToken) {
    }

    /** What a redirect needs: where to send the visitor, and which link to count the click for. */
    public record Redirect(Long linkId, String destination) {
    }

    public record DailyClicks(LocalDate date, long clicks) {
    }

    public record LinkStats(long totalClicks, List<DailyClicks> dailyClicks, Instant lastClickedAt) {
    }

    @Transactional
    public CreatedLink create(String url, String alias, Instant expiresAt) {
        destinationPolicy.validate(url);
        Instant now = now();
        Instant expiry = futureExpiry(expiresAt, now);

        String code;
        if (alias != null) {
            aliasPolicy.validate(alias);
            if (repository.existsByCode(alias)) {
                throw aliasTaken();
            }
            code = alias;
        } else {
            code = freshCode();
        }

        String token = tokenService.newToken();
        Link link = new Link(code, url, alias != null, now, expiry, tokenService.hash(token));
        try {
            repository.saveAndFlush(link);
        } catch (DataIntegrityViolationException e) {
            // Lost a race for the same code; for a generated code this is vanishingly rare.
            throw alias != null ? aliasTaken()
                    : new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "code_collision", "please retry");
        }
        return new CreatedLink(link, token);
    }

    /** Destination for an active link: 404 if unknown or deleted, 410 if expired. */
    @Transactional(readOnly = true)
    public String resolveForRedirect(String code) {
        return resolve(code).destination();
    }

    @Transactional(readOnly = true)
    public Redirect resolve(String code) {
        Link link = findLive(code);
        if (link.isExpiredAt(now())) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        return new Redirect(link.getId(), link.getOriginalUrl());
    }

    /**
     * Private stats (FR2): the same token rules as deletion. Expired links still have stats;
     * deleted ones do not. Daily counts cover the current UTC day and the previous 29, oldest
     * first, with zeroes for days without clicks.
     */
    @Transactional(readOnly = true)
    public LinkStats stats(String code, String managementToken) {
        Link link = findLive(code);
        authorize(link, managementToken);
        LocalDate today = LocalDate.ofInstant(now(), ZoneOffset.UTC);
        LocalDate from = today.minusDays(STATS_DAYS - 1);
        Map<LocalDate, Long> perDay = clicks.countPerDaySince(link.getId(), from).stream()
                .collect(Collectors.toMap(DailyCount::getDay, DailyCount::getClicks));
        List<DailyClicks> daily = new ArrayList<>(STATS_DAYS);
        for (LocalDate day = from; !day.isAfter(today); day = day.plusDays(1)) {
            daily.add(new DailyClicks(day, perDay.getOrDefault(day, 0L)));
        }
        return new LinkStats(clicks.countByLinkId(link.getId()), daily, clicks.findLastClickedAt(link.getId()));
    }

    /** Public metadata; expired links are still described, deleted ones are not. */
    @Transactional(readOnly = true)
    public Link metadata(String code) {
        return findLive(code);
    }

    /**
     * Sets a new expiry, or removes it when {@code expiresAt} is null. Under the link's row lock, like
     * deletion and click recording. Checks in order: 404 unknown or deleted, the token (401/403), 410
     * if already expired (an expired link is never revived), then the new value must be in the future
     * (400 invalid_expiry), as at creation; there is no maximum. Nothing changes unless all pass.
     */
    @Transactional
    public Link updateExpiry(String code, String managementToken, Instant expiresAt) {
        Link link = repository.lockByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
        authorize(link, managementToken);
        Instant now = now();
        if (link.isExpiredAt(now)) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        link.changeExpiry(futureExpiry(expiresAt, now));
        return repository.saveAndFlush(link);
    }

    /**
     * Tombstones the link and erases its clicks in one transaction (FR3), under the link's row
     * lock so a concurrent redirect cannot commit a click in between.
     */
    @Transactional
    public void delete(String code, String managementToken) {
        Link link = repository.lockByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
        authorize(link, managementToken);
        clicks.deleteByLinkId(link.getId());
        link.markDeleted(now());
        repository.save(link);
    }

    private void authorize(Link link, String managementToken) {
        if (managementToken == null || managementToken.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "missing_token", "X-Management-Token header is required");
        }
        if (!tokenService.matches(managementToken, link.getTokenHash())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "invalid_token", "management token does not match");
        }
    }

    /** Null stays null (no expiry); otherwise stored precision, and strictly after {@code now}. */
    private static Instant futureExpiry(Instant expiresAt, Instant now) {
        Instant expiry = expiresAt == null ? null : expiresAt.truncatedTo(ChronoUnit.MICROS);
        if (expiry != null && !expiry.isAfter(now)) {
            throw ApiException.badRequest("invalid_expiry", "expiresAt must be in the future");
        }
        return expiry;
    }

    private Link findLive(String code) {
        return repository.findByCode(code).filter(l -> !l.isDeleted()).orElseThrow(ApiException::notFound);
    }

    private String freshCode() {
        for (int i = 0; i < MAX_CODE_ATTEMPTS; i++) {
            String code = codeGenerator.next();
            // tombstones count as taken, so a deleted code is never handed out again
            if (!aliasPolicy.isReserved(code) && !repository.existsByCode(code)) {
                return code;
            }
        }
        throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "code_collision", "please retry");
    }

    private Instant now() {
        // the database stores microseconds; truncate so stored and returned timestamps agree
        return clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private static ApiException aliasTaken() {
        return new ApiException(HttpStatus.CONFLICT, "alias_taken", "alias is already in use");
    }
}

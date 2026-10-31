package com.example.shortener.service;

import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;

import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Link lifecycle: create, resolve for redirect, read metadata, delete into a tombstone. */
@Service
public class LinkService {

    static final int MAX_CODE_ATTEMPTS = 10;

    private final LinkRepository repository;
    private final DestinationPolicy destinationPolicy;
    private final AliasPolicy aliasPolicy;
    private final CodeGenerator codeGenerator;
    private final TokenService tokenService;
    private final Clock clock;

    public LinkService(LinkRepository repository, DestinationPolicy destinationPolicy, AliasPolicy aliasPolicy,
                       CodeGenerator codeGenerator, TokenService tokenService, Clock clock) {
        this.repository = repository;
        this.destinationPolicy = destinationPolicy;
        this.aliasPolicy = aliasPolicy;
        this.codeGenerator = codeGenerator;
        this.tokenService = tokenService;
        this.clock = clock;
    }

    /** The plaintext management token is returned here and nowhere else. */
    public record CreatedLink(Link link, String managementToken) {
    }

    @Transactional
    public CreatedLink create(String url, String alias, Instant expiresAt) {
        destinationPolicy.validate(url);
        Instant now = now();
        Instant expiry = expiresAt == null ? null : expiresAt.truncatedTo(ChronoUnit.MICROS);
        if (expiry != null && !expiry.isAfter(now)) {
            throw ApiException.badRequest("invalid_expiry", "expiresAt must be in the future");
        }

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
        Link link = findLive(code);
        if (link.isExpiredAt(now())) {
            throw new ApiException(HttpStatus.GONE, "expired", "link has expired");
        }
        return link.getOriginalUrl();
    }

    /** Public metadata; expired links are still described, deleted ones are not. */
    @Transactional(readOnly = true)
    public Link metadata(String code) {
        return findLive(code);
    }

    @Transactional
    public void delete(String code, String managementToken) {
        Link link = findLive(code);
        if (managementToken == null || managementToken.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "missing_token", "X-Management-Token header is required");
        }
        if (!tokenService.matches(managementToken, link.getTokenHash())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "invalid_token", "management token does not match");
        }
        link.markDeleted(now());
        repository.save(link);
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

package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.api.LinkDtos.CreateLinkRequest;
import com.example.shortener.api.LinkDtos.CreateLinkResponse;
import com.example.shortener.api.LinkDtos.LinkMetadata;
import com.example.shortener.api.LinkDtos.StatsResponse;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.ManagementTokenRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.CreatedLink;
import jakarta.servlet.http.HttpServletRequest;
import java.util.function.Supplier;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/links")
public class LinkController {

    static final String TOKEN_HEADER = "X-Management-Token";

    private final LinkService links;
    private final CreateRateLimiter rateLimiter;
    private final ManagementTokenRateLimiter tokenLimiter;

    public LinkController(LinkService links, CreateRateLimiter rateLimiter, ManagementTokenRateLimiter tokenLimiter) {
        this.links = links;
        this.rateLimiter = rateLimiter;
        this.tokenLimiter = tokenLimiter;
    }

    @PostMapping
    public ResponseEntity<CreateLinkResponse> create(@RequestBody CreateLinkRequest request, HttpServletRequest http) {
        if (request == null) {
            throw ApiException.badRequest("invalid_request", "request body is required");
        }
        // The network peer address: forwarding headers are client-controlled and not trusted.
        rateLimiter.acquire(http.getRemoteAddr());
        CreatedLink created = links.create(request.url(), request.alias(), request.expiresAt());
        String code = created.link().getCode();
        return ResponseEntity.created(URI.create("/api/links/" + code))
                .body(new CreateLinkResponse(code, "/" + code, created.managementToken()));
    }

    @GetMapping("/{code}")
    public LinkMetadata metadata(@PathVariable String code) {
        return LinkMetadata.of(links.metadata(code));
    }

    @GetMapping("/{code}/stats")
    public StatsResponse stats(@PathVariable String code,
                               @RequestHeader(name = TOKEN_HEADER, required = false) String token,
                               HttpServletRequest http) {
        return StatsResponse.of(withTokenThrottle(http, () -> links.stats(code, token)));
    }

    @DeleteMapping("/{code}")
    public ResponseEntity<Void> delete(@PathVariable String code,
                                       @RequestHeader(name = TOKEN_HEADER, required = false) String token,
                                       HttpServletRequest http) {
        withTokenThrottle(http, () -> {
            links.delete(code, token);
            return null;
        });
        return ResponseEntity.noContent().build();
    }

    /**
     * Runs a token-protected operation. A wrong token is counted against the caller's peer address and
     * stays 403 invalid_token until the limit is exceeded, then becomes 429 (FR10). Valid and missing
     * tokens are untouched: the existing contract decides those.
     */
    private <T> T withTokenThrottle(HttpServletRequest http, Supplier<T> operation) {
        try {
            return operation.get();
        } catch (ApiException e) {
            if ("invalid_token".equals(e.getError())) {
                tokenLimiter.recordFailure(http.getRemoteAddr());
            }
            throw e;
        }
    }
}

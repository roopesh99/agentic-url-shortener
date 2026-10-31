package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.api.LinkDtos.CreateLinkRequest;
import com.example.shortener.api.LinkDtos.CreateLinkResponse;
import com.example.shortener.api.LinkDtos.LinkMetadata;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.CreateRateLimiter;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.CreatedLink;
import jakarta.servlet.http.HttpServletRequest;
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

    public LinkController(LinkService links, CreateRateLimiter rateLimiter) {
        this.links = links;
        this.rateLimiter = rateLimiter;
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

    @DeleteMapping("/{code}")
    public ResponseEntity<Void> delete(@PathVariable String code,
                                       @RequestHeader(name = TOKEN_HEADER, required = false) String token) {
        links.delete(code, token);
        return ResponseEntity.noContent().build();
    }
}

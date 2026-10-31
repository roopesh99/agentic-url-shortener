package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.service.LinkService;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** The latency-sensitive path: one indexed lookup, then a 302. */
@RestController
public class RedirectController {

    private final LinkService links;

    public RedirectController(LinkService links) {
        this.links = links;
    }

    // Literal routes (/health, /api/...) take precedence over this pattern in Spring MVC.
    @GetMapping("/{code:[A-Za-z0-9_-]{3,32}}")
    public ResponseEntity<Void> redirect(@PathVariable String code) {
        URI destination = URI.create(links.resolveForRedirect(code));
        // no-store: links can expire or be deleted, so no client or proxy may cache the redirect
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(destination)
                .cacheControl(CacheControl.noStore())
                .build();
    }
}

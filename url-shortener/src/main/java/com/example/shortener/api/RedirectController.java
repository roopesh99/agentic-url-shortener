package com.example.shortener.api;

import java.net.URI;

import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.service.LinkService.Redirect;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** The latency-sensitive path: one indexed lookup, a best-effort click insert, then a 302. */
@RestController
public class RedirectController {

    private static final Logger log = LoggerFactory.getLogger(RedirectController.class);

    private final LinkService links;
    private final ClickRecorder clicks;

    public RedirectController(LinkService links, ClickRecorder clicks) {
        this.links = links;
        this.clicks = clicks;
    }

    // Literal routes (/health, /api/...) take precedence over this pattern in Spring MVC.
    @GetMapping("/{code:[A-Za-z0-9_-]{3,32}}")
    public ResponseEntity<Void> redirect(@PathVariable String code) {
        Redirect redirect = links.resolve(code);
        URI destination = URI.create(redirect.destination());
        try {
            clicks.record(redirect.linkId());
        } catch (RuntimeException e) {
            // Redirecting is the product; analytics are best-effort (NFR1). The click is lost, not the visit.
            log.warn("click not recorded: {}", e.getClass().getSimpleName());
        }
        // no-store: links can expire or be deleted, so no client or proxy may cache the redirect
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(destination)
                .cacheControl(CacheControl.noStore())
                .build();
    }
}

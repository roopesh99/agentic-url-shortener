package com.example.shortener;

import java.net.URI;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.support.ServletUriComponentsBuilder;

@RestController
public class ShortUrlController {

    private final ShortUrlService service;

    public ShortUrlController(ShortUrlService service) {
        this.service = service;
    }

    public record CreateRequest(String url) {}

    public record CreateResponse(String code, String shortUrl, String url) {}

    @PostMapping("/api/v1/urls")
    public ResponseEntity<CreateResponse> create(@RequestBody CreateRequest request) {
        String code = service.shorten(request.url());
        URI shortUrl = ServletUriComponentsBuilder.fromCurrentContextPath().path("/{code}").buildAndExpand(code).toUri();
        return ResponseEntity.created(shortUrl).body(new CreateResponse(code, shortUrl.toString(), request.url()));
    }

    @GetMapping("/{code:[0-9A-Za-z]{7}}")
    public ResponseEntity<Void> redirect(@PathVariable String code) {
        return service.resolve(code)
                .<ResponseEntity<Void>>map(url -> ResponseEntity.status(HttpStatus.FOUND).location(URI.create(url)).build())
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}

package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;

/** Standard bodies for errors that arrive as a bare status (framework errors, servlet error dispatch). */
final class ErrorBodies {

    private ErrorBodies() {
    }

    static ErrorResponse forStatus(int status) {
        return switch (status) {
            case 400 -> new ErrorResponse("invalid_request", "the request is not valid");
            case 404 -> new ErrorResponse("not_found", "no such resource");
            case 405 -> new ErrorResponse("method_not_allowed", "this method is not allowed here");
            case 413 -> new ErrorResponse("payload_too_large", "the request body is too large");
            case 415 -> new ErrorResponse("unsupported_media_type", "use Content-Type: application/json");
            case 503 -> new ErrorResponse("service_unavailable", "the service is temporarily unavailable; retry later");
            default -> status >= 500
                    ? new ErrorResponse("internal_error", "an unexpected error occurred")
                    : new ErrorResponse("invalid_request", "the request could not be processed");
        };
    }
}

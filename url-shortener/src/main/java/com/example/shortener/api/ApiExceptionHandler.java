package com.example.shortener.api;

import com.example.shortener.api.LinkDtos.ErrorResponse;
import com.example.shortener.service.ApiException;
import com.example.shortener.service.RateLimitedException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Every error is JSON {"error": <stable code>, "message": <human text>}. */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ApiException.class)
    ResponseEntity<ErrorResponse> api(ApiException e) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(e.getStatus());
        if (e instanceof RateLimitedException limited) {
            response.header(HttpHeaders.RETRY_AFTER, Long.toString(limited.getRetryAfterSeconds()));
        }
        return response.body(new ErrorResponse(e.getError(), e.getMessage()));
    }

    /** Malformed JSON, or a field of the wrong type such as an unparseable expiresAt. */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ErrorResponse> unreadable(HttpMessageNotReadableException e) {
        return ResponseEntity.badRequest()
                .body(new ErrorResponse("invalid_request", "request body is not valid JSON for this endpoint"));
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<ErrorResponse> mediaType(HttpMediaTypeNotSupportedException e) {
        return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE)
                .body(new ErrorResponse("unsupported_media_type", "use Content-Type: application/json"));
    }
}

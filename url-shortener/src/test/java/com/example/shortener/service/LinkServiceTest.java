package com.example.shortener.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.security.SecureRandom;

import com.example.shortener.domain.Link;
import com.example.shortener.domain.LinkRepository;
import com.example.shortener.support.MutableClock;
import com.example.shortener.support.StubHostResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class LinkServiceTest {

    private LinkRepository repository;
    private CodeGenerator codes;
    private LinkService service;

    @BeforeEach
    void setUp() {
        repository = mock(LinkRepository.class);
        codes = mock(CodeGenerator.class);
        when(repository.saveAndFlush(any(Link.class))).thenAnswer(invocation -> invocation.getArgument(0));
        service = new LinkService(repository, new DestinationPolicy(new StubHostResolver()), new AliasPolicy(), codes,
                new TokenService(new SecureRandom()), new MutableClock());
    }

    /** TC-FR1-05: active and tombstoned codes both count as taken; the first unused code wins. */
    @Test
    void TC_FR1_05_collidingGeneratedCodesAreRetried() {
        when(codes.next()).thenReturn("ActiveC1", "Tombstn2", "FreeCod3");
        when(repository.existsByCode("ActiveC1")).thenReturn(true);  // an active link
        when(repository.existsByCode("Tombstn2")).thenReturn(true);  // a deleted link's tombstone
        when(repository.existsByCode("FreeCod3")).thenReturn(false);

        LinkService.CreatedLink created = service.create("https://example.com/x", null, null);

        assertThat(created.link().getCode()).isEqualTo("FreeCod3");
        assertThat(created.link().isCustomAlias()).isFalse();
    }

    @Test
    void TC_FR1_05_generationGivesUpAfterBoundedAttempts() {
        when(codes.next()).thenReturn("Taken000");
        when(repository.existsByCode("Taken000")).thenReturn(true);

        assertThatThrownBy(() -> service.create("https://example.com/x", null, null))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.getStatus()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE));
        verify(repository, never()).saveAndFlush(any());
    }

    @Test
    void TC_FR1_05_reservedWordsAreNeverHandedOutAsGeneratedCodes() {
        when(codes.next()).thenReturn("HEALTH", "FreeCod4");
        when(repository.existsByCode(any())).thenReturn(false);
        assertThat(service.create("https://example.com/x", null, null).link().getCode()).isEqualTo("FreeCod4");
    }
}

package com.example.shortener.support;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/**
 * Replaces the production clock and DNS resolver with controllable test doubles. Each double is
 * the primary bean of its type (MutableClock is a Clock, StubHostResolver a HostResolver).
 */
@TestConfiguration
public class TestSupportConfig {

    @Bean
    @Primary
    public MutableClock testClock() {
        return new MutableClock();
    }

    @Bean
    @Primary
    public StubHostResolver stubHostResolver() {
        return new StubHostResolver();
    }
}

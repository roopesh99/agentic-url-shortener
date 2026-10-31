package com.example.shortener.config;

import java.net.InetAddress;
import java.security.SecureRandom;
import java.time.Clock;

import com.example.shortener.service.HostResolver;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Time, randomness and DNS are injectable seams so behaviour is deterministic under test. */
@Configuration
public class AppConfig {

    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }

    @Bean
    SecureRandom secureRandom() {
        return new SecureRandom();
    }

    @Bean
    HostResolver hostResolver() {
        return InetAddress::getAllByName;
    }
}

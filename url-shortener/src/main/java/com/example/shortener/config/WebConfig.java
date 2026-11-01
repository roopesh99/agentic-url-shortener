package com.example.shortener.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.api.RedirectMetricsInterceptor;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** Filters and interceptors for the public web server. */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final RedirectMetricsInterceptor redirectMetrics;

    public WebConfig(RedirectMetricsInterceptor redirectMetrics) {
        this.redirectMetrics = redirectMetrics;
    }

    @Bean
    FilterRegistrationBean<SecurityHeadersFilter> securityHeadersFilter() {
        FilterRegistrationBean<SecurityHeadersFilter> registration = new FilterRegistrationBean<>(new SecurityHeadersFilter());
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE); // first, so even rejected requests carry the headers
        return registration;
    }

    @Bean
    FilterRegistrationBean<ApiBodyLimitFilter> apiBodyLimitFilter(ShortenerProperties properties, ObjectMapper json) {
        FilterRegistrationBean<ApiBodyLimitFilter> registration =
                new FilterRegistrationBean<>(new ApiBodyLimitFilter(properties.maxApiBodyBytes(), json));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
        return registration;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(redirectMetrics); // it ignores every handler except the redirect
    }
}

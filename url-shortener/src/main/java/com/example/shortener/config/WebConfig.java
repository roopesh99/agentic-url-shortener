package com.example.shortener.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.api.ApiErrorReportValve;
import com.example.shortener.api.RedirectMetricsInterceptor;
import org.apache.catalina.core.StandardHost;
import org.apache.catalina.startup.Tomcat;
import org.springframework.boot.web.embedded.tomcat.TomcatServletWebServerFactory;
import org.springframework.boot.web.embedded.tomcat.TomcatWebServer;
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

    /** The embedded Tomcat, with the JSON error-report valve in place of its HTML one. */
    @Bean
    TomcatServletWebServerFactory tomcatServletWebServerFactory() {
        return new JsonErrorTomcatFactory();
    }

    /**
     * Errors Tomcat produces before the application sees the request (a malformed request target)
     * are rendered by the host's error-report valve; naming the valve class before the server starts
     * makes them use the API's JSON error body. A named class, because the management server is
     * created from the same factory type: its errors become JSON as well.
     */
    public static class JsonErrorTomcatFactory extends TomcatServletWebServerFactory {

        @Override
        protected TomcatWebServer getTomcatWebServer(Tomcat tomcat) {
            ((StandardHost) tomcat.getHost()).setErrorReportValveClass(ApiErrorReportValve.class.getName());
            return super.getTomcatWebServer(tomcat);
        }
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(redirectMetrics); // it ignores every handler except the redirect
    }
}

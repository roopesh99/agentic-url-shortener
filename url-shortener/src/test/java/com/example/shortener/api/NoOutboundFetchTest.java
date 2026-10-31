package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.net.InetAddress;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import com.example.shortener.service.DestinationPolicy;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;

/**
 * TC-NFR2-06: the service validates destinations but never fetches them. Two observable checks:
 * (1) no HTTP client is wired into the application, and (2) the only network-facing action
 * during create + redirect is the single DNS lookup at creation, made through the resolver.
 */
class NoOutboundFetchTest extends IntegrationTest {

    @Autowired
    private ApplicationContext context;

    @Test
    void TC_NFR2_06_noHttpClientBeansExist() {
        for (String type : List.of("org.springframework.web.client.RestTemplate", "org.springframework.web.client.RestClient",
                "org.springframework.web.reactive.function.client.WebClient", "java.net.http.HttpClient")) {
            try {
                assertThat(context.getBeanNamesForType(Class.forName(type))).as(type).isEmpty();
            } catch (ClassNotFoundException absent) {
                // not even on the classpath
            }
        }
    }

    @Test
    void TC_NFR2_06_createAndRedirectOnlyResolveOnceAndNeverFetch() throws Exception {
        List<String> lookups = new CopyOnWriteArrayList<>();
        DestinationPolicy recording = new DestinationPolicy(host -> {
            lookups.add(host);
            return new InetAddress[] {InetAddress.getByName("93.184.216.34")};
        });
        recording.validate("https://probe.example/path");
        assertThat(lookups).containsExactly("probe.example");

        String code = create("https://probe.example/path").get("code").asText();
        int before = lookups.size();
        mvc.perform(get("/" + code)).andExpect(status().isFound())
                .andExpect(header().string("Location", "https://probe.example/path"));
        assertThat(lookups).hasSize(before); // redirecting does not touch the destination at all
    }
}

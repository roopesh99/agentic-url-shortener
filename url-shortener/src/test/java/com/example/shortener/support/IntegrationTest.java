package com.example.shortener.support;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.domain.LinkRepository;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * Full Spring context over an isolated in-memory H2 database (migrated by Flyway), with a
 * controllable clock and stubbed DNS. The rate limit is raised so only the dedicated rate-limit
 * tests exercise it. Tests use unique aliases and URLs, so they stay independent while sharing
 * the cached context.
 */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:it-${random.uuid};DB_CLOSE_DELAY=-1",
        "shortener.rate-limit.creates-per-minute=1000000"
})
@AutoConfigureMockMvc
@Import(TestSupportConfig.class)
public abstract class IntegrationTest {

    @Autowired
    protected MockMvc mvc;

    @Autowired
    protected ObjectMapper json;

    @Autowired
    protected MutableClock clock;

    @Autowired
    protected StubHostResolver resolver;

    @Autowired
    protected LinkRepository repository;

    @BeforeEach
    void resetDoubles() {
        clock.set(MutableClock.START);
        resolver.answers.clear();
        resolver.failing.clear();
    }

    protected static String uniqueAlias(String prefix) {
        return prefix + "-" + Long.toString(ThreadLocalRandom.current().nextLong(Long.MAX_VALUE), 36);
    }

    protected ResultActions postLink(Map<String, ?> body) throws Exception {
        return mvc.perform(post("/api/links").contentType(MediaType.APPLICATION_JSON)
                .content(json.writeValueAsString(body)));
    }

    /** Creates a link and returns the parsed 201 response (code, shortPath, managementToken). */
    protected JsonNode create(String url, String alias, String expiresAt) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("url", url);
        if (alias != null) {
            body.put("alias", alias);
        }
        if (expiresAt != null) {
            body.put("expiresAt", expiresAt);
        }
        String response = postLink(body).andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        return json.readTree(response);
    }

    protected JsonNode create(String url) throws Exception {
        return create(url, null, null);
    }
}

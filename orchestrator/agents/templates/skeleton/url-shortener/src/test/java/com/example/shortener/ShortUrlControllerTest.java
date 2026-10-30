package com.example.shortener;

import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class ShortUrlControllerTest {

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper json;

    // TC-FR1-01: create returns 201 with a 7-char Base62 code
    @Test
    void createsShortUrl() throws Exception {
        mvc.perform(post("/api/v1/urls").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"url\":\"https://example.com/a/long/path\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.code").value(matchesPattern("[0-9A-Za-z]{7}")));
    }

    // TC-FR3-01: visiting the short link redirects (302) to the original URL
    @Test
    void redirectsToOriginalUrl() throws Exception {
        String body = mvc.perform(post("/api/v1/urls").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"url\":\"https://example.com/target\"}"))
                .andReturn().getResponse().getContentAsString();
        JsonNode created = json.readTree(body);

        mvc.perform(get("/" + created.get("code").asText()))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "https://example.com/target"));
    }

    // TC-FR3-02: unknown code returns 404
    @Test
    void unknownCodeReturns404() throws Exception {
        mvc.perform(get("/Zz00000")).andExpect(status().isNotFound());
    }

    // TC-NFR2-01: non-http(s) schemes are rejected
    @Test
    void rejectsNonHttpScheme() throws Exception {
        mvc.perform(post("/api/v1/urls").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"url\":\"javascript:alert(1)\"}"))
                .andExpect(status().isBadRequest());
    }
}

package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;

class HealthTest {

    @Nested
    class WithRunningServiceAndStore extends IntegrationTest {

        @Test
        void TC_FR6_01_healthyServiceReturns200Up() throws Exception {
            mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("UP"));
        }
    }

    /**
     * TC-FR6-02: the persistence check failing while the app keeps running. The controller is
     * exercised directly with a store that refuses connections; stopping the shared test
     * database would break every other test in the context.
     */
    @Test
    void TC_FR6_02_unavailableStoreReturns503Down() {
        JdbcTemplate failing = mock(JdbcTemplate.class);
        when(failing.queryForObject(anyString(), eq(Integer.class)))
                .thenThrow(new DataAccessResourceFailureException("connection refused"));

        var response = new HealthController(failing).health();

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(response.getBody()).containsEntry("status", "DOWN");
    }
}

package com.example.shortener.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.shortener.service.ClickRecorder;
import com.example.shortener.service.LinkService;
import com.example.shortener.support.IntegrationTest;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

/** NFR1: analytics are best-effort; a failure to record a click never changes the redirect. */
class ClickFailureIsolationTest {

    /** TC-FR1-03: the controller alone, with a recorder that throws. */
    @Test
    void TC_FR1_03_recorderFailureStillReturnsTheRedirect() {
        LinkService links = mock(LinkService.class);
        ClickRecorder recorder = mock(ClickRecorder.class);
        when(links.resolve("abc12345")).thenReturn(new LinkService.Redirect(7L, "https://example.com/x"));
        doThrow(new DataAccessResourceFailureException("click store down")).when(recorder).record(any());

        var response = new RedirectController(links, recorder).redirect("abc12345");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FOUND);
        assertThat(response.getHeaders().getLocation()).hasToString("https://example.com/x");
        assertThat(response.getHeaders().getCacheControl()).contains("no-store");
    }

    /** TC-NFR1-01: the same failure through the running application. */
    @Nested
    class ThroughTheRunningApplication extends IntegrationTest {

        @MockitoBean
        private ClickRecorder recorder;

        @Test
        void TC_NFR1_01_redirectIsUnchangedWhenClickPersistenceFails() throws Exception {
            doThrow(new DataAccessResourceFailureException("click store down")).when(recorder).record(any());
            String code = create("https://example.com/nfr1-01").get("code").asText();
            mvc.perform(get("/" + code))
                    .andExpect(status().isFound())
                    .andExpect(header().string("Location", "https://example.com/nfr1-01"))
                    .andExpect(header().string("Cache-Control", containsString("no-store")));
        }
    }
}

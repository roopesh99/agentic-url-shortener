package com.example.shortener.api;

import java.io.IOException;
import java.io.Writer;
import java.util.concurrent.atomic.AtomicBoolean;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.catalina.connector.Request;
import org.apache.catalina.connector.Response;
import org.apache.catalina.valves.ErrorReportValve;
import org.apache.coyote.ActionCode;

/**
 * Renders the errors the embedded server produces itself (for example a malformed percent-escape,
 * rejected before the request reaches the application) as the API's JSON error body instead of
 * Tomcat's HTML page. Same rules as Tomcat's own valve: only for an error status, only if nothing
 * has been written, status and other headers unchanged. Errors the application already rendered
 * are left alone.
 */
public class ApiErrorReportValve extends ErrorReportValve {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Override
    protected void report(Request request, Response response, Throwable throwable) {
        int status = response.getStatus();
        if (status < 400 || response.getContentWritten() > 0 || !response.setErrorReported()) {
            return;
        }
        AtomicBoolean ioAllowed = new AtomicBoolean(true);
        response.getCoyoteResponse().action(ActionCode.IS_IO_ALLOWED, ioAllowed);
        if (!ioAllowed.get()) {
            return; // the connection is already unusable; there is no one to write to
        }
        try {
            response.setContentType("application/json");
            response.setCharacterEncoding("UTF-8");
            Writer writer = response.getReporter();
            if (writer != null) {
                writer.write(JSON.writeValueAsString(ErrorBodies.forStatus(status)));
                response.finishResponse();
            }
        } catch (IOException | IllegalStateException e) {
            // the client went away or the response was committed meanwhile: nothing more can be sent
        }
    }
}

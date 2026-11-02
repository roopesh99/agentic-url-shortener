package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assumptions.assumeThat;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.ConnectException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.example.shortener.support.SecurityHeaders;
import com.example.shortener.support.TestSupportConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.junit.jupiter.api.extension.ExtendWith;

/**
 * Real listeners on real ports: FR15 (loopback-only management server exposing only health and
 * metrics), FR13 on the management server, FR17/NFR3 (no visitor data in logs), and pre-MVC
 * malformed-target error responses.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.datasource.url=jdbc:h2:mem:mgmt-${random.uuid};DB_CLOSE_DELAY=-1",
        "management.server.port=0"
})
@Import(TestSupportConfig.class)
@ExtendWith(OutputCaptureExtension.class)
class ManagementServerTest {

    private final HttpClient http = HttpClient.newHttpClient();

    @LocalServerPort
    private int port;

    @LocalManagementPort
    private int managementPort;

    @Value("${management.server.address}")
    private String managementAddress;

    @Test
    void TC_FR15_01_onlyHealthAndMetricsOnTheLoopbackManagementPort() throws Exception {
        assertThat(managementAddress).isEqualTo("127.0.0.1");
        assertThat(managementPort).isNotEqualTo(port);
        assertThat(call("127.0.0.1", managementPort, "/actuator/health").statusCode()).isEqualTo(200);
        assertThat(call("127.0.0.1", managementPort, "/actuator/metrics").statusCode()).isEqualTo(200);
        for (String hidden : new String[] {"/actuator/env", "/actuator/beans", "/actuator/configprops", "/actuator/heapdump"}) {
            assertThat(call("127.0.0.1", managementPort, hidden).statusCode()).as(hidden).isEqualTo(404);
        }
        assertThat(call("127.0.0.1", port, "/actuator/health").statusCode()).as("not on the public port").isEqualTo(404);
    }

    @Test
    void TC_FR15_01_managementPortIsUnreachableFromANonLoopbackAddress() {
        Optional<InetAddress> external = nonLoopbackIPv4();
        assumeThat(external).as("this machine has a non-loopback IPv4 address").isPresent();
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(external.get(), managementPort), 2_000);
            throw new AssertionError("management port accepted a connection on " + external.get());
        } catch (ConnectException expected) {
            // refused: nothing listens there
        } catch (IOException other) {
            // also unreachable (e.g. timeout)
        }
    }

    @Test
    void TC_FR13_01_managementResponsesCarryTheSecurityHeadersToo() throws Exception {
        HttpResponse<String> health = call("127.0.0.1", managementPort, "/actuator/health");
        SecurityHeaders.EXPECTED.forEach((name, value) ->
                assertThat(health.headers().firstValue(name)).as(name).hasValue(value));
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/links/%", "/api/links/%A"})
    void TC_FR1_02_incompletePercentEscapesReturnTheDocumentedJsonBadRequest(String target) throws Exception {
        assertDocumentedBadRequest(rawGet(target));
    }

    @Test
    void TC_FR1_01_malformedPercentEscapeOnApiPathReturnsTheDocumentedJsonBadRequest() throws Exception {
        assertDocumentedBadRequest(rawGet("/api/links/%ZZ"));
    }

    @Test
    void TC_FR2_01_malformedPercentEscapeOnRedirectPathAlsoReturnsTheDocumentedJsonBadRequest() throws Exception {
        assertDocumentedBadRequest(rawGet("/%ZZ"));
    }

    @Test
    void TC_FR3_01_validPublicRequestKeepsItsStatusHeadersAndBody() throws Exception {
        RawResponse response = rawGet("/health");

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.header("content-type")).startsWith("application/json");
        assertThat(response.body()).isEqualTo("{\"status\":\"UP\"}");
        SecurityHeaders.EXPECTED.forEach((name, value) ->
                assertThat(response.header(name.toLowerCase())).as(name).isEqualTo(value));
    }

    @Test
    void TC_FR17_01_noVisitorDataReachesTheLogs(CapturedOutput output) throws Exception {
        for (String path : new String[] {"/Zz9Zz9Zz", "/no/such/route", "/api/links/Zz9Zz9Zz/stats"}) {
            http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                    .header("User-Agent", "LogProbe-Agent/1.0").header("X-Forwarded-For", "203.0.113.177")
                    .header("X-Management-Token", "probe-token-value").header("Cookie", "probe=cookie-value").build(),
                    HttpResponse.BodyHandlers.discarding());
        }
        for (String probe : new String[] {"LogProbe-Agent", "203.0.113.177", "probe-token-value", "cookie-value", "Zz9Zz9Zz"}) {
            assertThat(output.getAll()).as(probe).doesNotContain(probe);
        }
    }

    private void assertDocumentedBadRequest(RawResponse response) throws Exception {
        assertThat(response.status()).isEqualTo(400);
        assertThat(response.header("content-type")).startsWith("application/json");

        JsonNode body = new ObjectMapper().readTree(response.body());
        Set<String> fields = new java.util.HashSet<>();
        body.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("error", "message");
        assertThat(body.get("error").asText()).isEqualTo("invalid_request");
        assertThat(body.get("message").asText()).isEqualTo("the request is not valid");
    }

    /** Sends the request target verbatim, without URI/client-side percent-escape validation. */
    private RawResponse rawGet(String target) throws IOException {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress("127.0.0.1", port), 2_000);
            socket.setSoTimeout(5_000);
            String request = "GET " + target + " HTTP/1.1\r\n"
                    + "Host: 127.0.0.1:" + port + "\r\n"
                    + "Connection: close\r\n\r\n";
            socket.getOutputStream().write(request.getBytes(StandardCharsets.US_ASCII));
            return parseResponse(socket.getInputStream().readAllBytes());
        }
    }

    private static RawResponse parseResponse(byte[] bytes) {
        String wire = new String(bytes, StandardCharsets.ISO_8859_1);
        int headerEnd = wire.indexOf("\r\n\r\n");
        if (headerEnd < 0) {
            throw new AssertionError("HTTP response did not contain a header terminator");
        }

        String[] lines = wire.substring(0, headerEnd).split("\r\n");
        int status = Integer.parseInt(lines[0].split(" ", 3)[1]);
        Map<String, String> headers = new HashMap<>();
        for (int i = 1; i < lines.length; i++) {
            int separator = lines[i].indexOf(':');
            if (separator > 0) {
                headers.put(lines[i].substring(0, separator).toLowerCase(), lines[i].substring(separator + 1).trim());
            }
        }

        String body = wire.substring(headerEnd + 4);
        if ("chunked".equalsIgnoreCase(headers.get("transfer-encoding"))) {
            body = decodeChunkedBody(body);
        } else if (headers.containsKey("content-length")) {
            body = body.substring(0, Math.min(body.length(), Integer.parseInt(headers.get("content-length"))));
        }
        return new RawResponse(status, headers, body);
    }

    private static String decodeChunkedBody(String chunked) {
        StringBuilder body = new StringBuilder();
        int cursor = 0;
        while (cursor < chunked.length()) {
            int lineEnd = chunked.indexOf("\r\n", cursor);
            if (lineEnd < 0) {
                break;
            }
            String sizeLine = chunked.substring(cursor, lineEnd);
            int extension = sizeLine.indexOf(';');
            int size = Integer.parseInt(extension < 0 ? sizeLine : sizeLine.substring(0, extension), 16);
            if (size == 0) {
                break;
            }
            cursor = lineEnd + 2;
            body.append(chunked, cursor, cursor + size);
            cursor += size + 2;
        }
        return body.toString();
    }

    private record RawResponse(int status, Map<String, String> headers, String body) {
        String header(String name) {
            return headers.get(name.toLowerCase());
        }
    }

    private HttpResponse<String> call(String host, int targetPort, String path) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create("http://" + host + ":" + targetPort + path)).build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private static Optional<InetAddress> nonLoopbackIPv4() {
        try {
            return Collections.list(NetworkInterface.getNetworkInterfaces()).stream()
                    .flatMap(nic -> Collections.list(nic.getInetAddresses()).stream())
                    .filter(a -> a instanceof Inet4Address && !a.isLoopbackAddress() && !a.isLinkLocalAddress())
                    .findFirst();
        } catch (IOException e) {
            return Optional.empty();
        }
    }
}

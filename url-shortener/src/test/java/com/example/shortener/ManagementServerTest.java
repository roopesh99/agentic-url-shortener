package com.example.shortener;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assumptions.assumeThat;

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
import java.util.Collections;
import java.util.Optional;

import com.example.shortener.support.SecurityHeaders;
import com.example.shortener.support.TestSupportConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;

/**
 * Real listeners on real ports: FR15 (loopback-only management server exposing only health and
 * metrics), FR13 on the management server, and FR17/NFR3 (no visitor data in logs).
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

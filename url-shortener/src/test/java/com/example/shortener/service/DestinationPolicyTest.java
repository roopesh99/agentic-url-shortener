package com.example.shortener.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;

import com.example.shortener.support.StubHostResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class DestinationPolicyTest {

    private StubHostResolver resolver;
    private DestinationPolicy policy;

    @BeforeEach
    void setUp() {
        resolver = new StubHostResolver();
        policy = new DestinationPolicy(resolver);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "http://localhost/", "http://LOCALHOST:8080/x", "http://api.localhost/",
            "http://127.0.0.1/", "http://127.255.0.9/", "http://0.0.0.0/",
            "http://10.0.0.1/", "http://172.16.5.4/", "http://172.31.255.255/", "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data", "http://224.0.0.1/", "http://239.255.255.250/",
            "http://[::1]/", "http://[::]/", "http://[fe80::1]/", "http://[fc00::1]/", "http://[fd12:3456::7]/",
            "http://[ff02::1]/", "http://[::ffff:127.0.0.1]/"
    })
    void TC_NFR2_02_localhostAndProhibitedLiteralsAreRejected(String url) {
        assertThatThrownBy(() -> policy.validate(url)).isInstanceOfSatisfying(ApiException.class,
                e -> assertThat(e.getError()).isEqualTo("prohibited_destination"));
    }

    @Test
    void TC_NFR2_03_hostnameResolvingOnlyToProhibitedAddressesIsRejected() {
        resolver.answers.put("intranet.example", List.of("10.1.2.3", "fd00::5"));
        assertThatThrownBy(() -> policy.validate("https://intranet.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_03_mixedPublicAndProhibitedResultsAreRejected() {
        resolver.answers.put("rebind.example", List.of(StubHostResolver.PUBLIC_IP, "127.0.0.1"));
        resolver.answers.put("rebind6.example", List.of("2606:2800:220:1:248:1893:25c8:1946", "fe80::1"));
        assertThatThrownBy(() -> policy.validate("https://rebind.example/")).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> policy.validate("https://rebind6.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_04_resolutionFailureOrNoAddressesFailsClosed() {
        resolver.failing.put("timeout.example", true);
        assertThatThrownBy(() -> policy.validate("https://timeout.example/"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.getError()).isEqualTo("invalid_url"));

        DestinationPolicy empty = new DestinationPolicy(host -> new InetAddress[0]);
        assertThatThrownBy(() -> empty.validate("https://empty.example/")).isInstanceOf(ApiException.class);

        DestinationPolicy nulls = new DestinationPolicy(host -> null);
        assertThatThrownBy(() -> nulls.validate("https://null.example/")).isInstanceOf(ApiException.class);

        DestinationPolicy throwing = new DestinationPolicy(host -> {
            throw new UnknownHostException("SERVFAIL");
        });
        assertThatThrownBy(() -> throwing.validate("https://servfail.example/")).isInstanceOf(ApiException.class);
    }

    @Test
    void TC_NFR2_05_publicDestinationsAreAccepted() {
        resolver.answers.put("dual.example", List.of(StubHostResolver.PUBLIC_IP, "2606:2800:220:1:248:1893:25c8:1946"));
        String prefix = "https://dual.example/";
        String longest = prefix + "p".repeat(2048 - prefix.length());

        for (String url : List.of("http://example.com", "https://example.com/path?q=1#frag", "HTTPS://Example.COM/x",
                "https://dual.example/", "http://93.184.216.34/", "http://[2606:2800:220:1:248:1893:25c8:1946]/", longest)) {
            assertThatCode(() -> policy.validate(url)).as(url).doesNotThrowAnyException();
        }
    }

    @Test
    void TC_NFR2_05_lengthLimitIsExclusiveAbove2048() {
        String prefix = "https://example.com/";
        assertThatThrownBy(() -> policy.validate(prefix + "p".repeat(2049 - prefix.length())))
                .isInstanceOf(ApiException.class);
    }
}

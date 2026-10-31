package com.example.shortener.support;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;

import com.example.shortener.service.HostResolver;

/**
 * Deterministic DNS: IP literals are parsed (no lookup happens for literals), names listed in
 * {@link #answers} resolve as configured, names in {@link #failing} fail, and any other name
 * resolves to a single public address. Tests never touch real DNS.
 */
public class StubHostResolver implements HostResolver {

    public static final String PUBLIC_IP = "93.184.216.34";
    private static final Pattern IP_LITERAL = Pattern.compile("[0-9.]+|.*:.*");

    public final Map<String, List<String>> answers = new ConcurrentHashMap<>();
    public final Map<String, Boolean> failing = new ConcurrentHashMap<>();

    @Override
    public InetAddress[] resolve(String host) throws UnknownHostException {
        if (IP_LITERAL.matcher(host).matches()) {
            return new InetAddress[] {InetAddress.getByName(host)};
        }
        if (failing.containsKey(host)) {
            throw new UnknownHostException(host);
        }
        List<String> ips = answers.getOrDefault(host, List.of(PUBLIC_IP));
        InetAddress[] out = new InetAddress[ips.size()];
        for (int i = 0; i < ips.size(); i++) {
            out[i] = InetAddress.getByName(ips.get(i)); // literals only: no DNS
        }
        return out;
    }
}

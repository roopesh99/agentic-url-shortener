package com.example.shortener.service;

import java.net.InetAddress;
import java.net.UnknownHostException;

/** DNS lookup seam: production uses the system resolver; tests substitute fixed answers. */
@FunctionalInterface
public interface HostResolver {

    InetAddress[] resolve(String host) throws UnknownHostException;
}

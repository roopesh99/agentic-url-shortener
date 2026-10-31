package com.example.shortener.service;

import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

/** Custom alias rules: 3-32 characters from [A-Za-z0-9_-], case-sensitive, not a reserved path. */
@Component
public class AliasPolicy {

    private static final Pattern ALIAS = Pattern.compile("[A-Za-z0-9_-]{3,32}");

    /** Top-level paths the service itself uses. Checked case-insensitively so "API" can't shadow "api". */
    static final Set<String> RESERVED = Set.of("api", "health", "links", "error", "actuator");

    public void validate(String alias) {
        if (!ALIAS.matcher(alias).matches()) {
            throw ApiException.badRequest("invalid_alias",
                    "alias must be 3-32 characters from letters, digits, '_' and '-'");
        }
        if (isReserved(alias)) {
            throw ApiException.badRequest("reserved_alias", "alias '" + alias + "' is reserved");
        }
    }

    public boolean isReserved(String code) {
        return RESERVED.contains(code.toLowerCase(Locale.ROOT));
    }
}

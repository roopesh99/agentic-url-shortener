package com.example.shortener.domain;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

public interface LinkRepository extends JpaRepository<Link, Long> {

    /** Includes tombstones: a deleted code is still "taken". */
    Optional<Link> findByCode(String code);

    boolean existsByCode(String code);
}

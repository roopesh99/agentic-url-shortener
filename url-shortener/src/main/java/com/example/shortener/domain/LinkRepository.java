package com.example.shortener.domain;

import java.util.Optional;

import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface LinkRepository extends JpaRepository<Link, Long> {

    /** Includes tombstones: a deleted code is still "taken". */
    Optional<Link> findByCode(String code);

    boolean existsByCode(String code);

    /**
     * Reads the link under a row lock (SELECT ... FOR UPDATE) for the rest of the transaction.
     * Click recording and deletion both take it, so a click can never be committed after the
     * deletion that erased the link's clicks.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select l from Link l where l.id = :id")
    Optional<Link> lockById(@Param("id") Long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select l from Link l where l.code = :code")
    Optional<Link> lockByCode(@Param("code") String code);
}

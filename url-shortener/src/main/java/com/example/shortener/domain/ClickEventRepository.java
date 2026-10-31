package com.example.shortener.domain;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ClickEventRepository extends JpaRepository<ClickEvent, Long> {

    long countByLinkId(Long linkId);

    @Query("select max(c.clickedAt) from ClickEvent c where c.linkId = :linkId")
    Instant findLastClickedAt(@Param("linkId") Long linkId);

    /** Days with at least one click from {@code from} onward; the caller fills in the empty days. */
    @Query("select c.clickDate as day, count(c) as clicks from ClickEvent c "
            + "where c.linkId = :linkId and c.clickDate >= :from group by c.clickDate")
    List<DailyCount> countPerDaySince(@Param("linkId") Long linkId, @Param("from") LocalDate from);

    @Modifying
    @Query("delete from ClickEvent c where c.linkId = :linkId")
    int deleteByLinkId(@Param("linkId") Long linkId);

    interface DailyCount {
        LocalDate getDay();

        long getClicks();
    }
}

-- Backfill metacognition_log.course_id for rows written before 022_tenancy_columns.
--
-- 022 added the column as TEXT NOT NULL DEFAULT 'default', so every pre-existing
-- row was stranded at 'default'. The course-scoped calibration queries
-- (get_scaffold_level, get_reference_class, get_calibration_metrics) match on the
-- real course id, so a learner's whole estimation history became invisible and the
-- scaffold silently reverted to 'full'.
--
-- effort:* rows key item_id to deadline_cache.id, so their scope is recoverable.
-- Rows whose deadline has since left the cache cannot be mapped and stay at
-- 'default'. confidence:* rows are left alone: they carry the course in the
-- domain suffix and no query reads their course_id column.

UPDATE metacognition_log
SET course_id = (
    SELECT CAST(deadline_cache.course_id AS TEXT)
    FROM deadline_cache
    WHERE deadline_cache.id = metacognition_log.item_id
)
WHERE domain LIKE 'effort:%'
  AND course_id = 'default'
  AND EXISTS (
    SELECT 1
    FROM deadline_cache
    WHERE deadline_cache.id = metacognition_log.item_id
  );

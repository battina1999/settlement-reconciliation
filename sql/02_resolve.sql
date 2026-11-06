-- Reconsider every incoming ID, regardless of the business date or arrival order.
-- Equal revision + different canonical payload is a conflict, so payload is NULL.
DELETE FROM current_records
USING changed_keys
WHERE current_records.kind = changed_keys.kind
  AND current_records.record_id = changed_keys.record_id;

INSERT INTO current_records
WITH touched AS (
    SELECT raw_records.*
    FROM raw_records JOIN changed_keys USING (kind, record_id)
), highest_revision AS (
    SELECT kind, record_id, max(revision) AS revision
    FROM touched GROUP BY kind, record_id
)
SELECT kind, record_id, revision,
       count(DISTINCT payload_hash) AS variant_count,
       count(*) AS occurrence_count,
       CASE WHEN count(DISTINCT payload_hash) = 1
            THEN first(payload ORDER BY payload_hash) END AS payload
FROM touched JOIN highest_revision USING (kind, record_id, revision)
GROUP BY kind, record_id, revision;

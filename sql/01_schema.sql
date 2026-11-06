CREATE SEQUENCE IF NOT EXISTS batch_sequence START 1;
CREATE TABLE IF NOT EXISTS batches (
    batch_id BIGINT PRIMARY KEY DEFAULT nextval('batch_sequence'),
    kind VARCHAR NOT NULL,
    sha256 VARCHAR NOT NULL,
    filename VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    UNIQUE (kind, sha256)
);
CREATE TABLE IF NOT EXISTS raw_records (
    batch_id BIGINT NOT NULL REFERENCES batches(batch_id),
    row_number BIGINT NOT NULL,
    kind VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    revision BIGINT NOT NULL,
    payload JSON NOT NULL,
    payload_hash VARCHAR NOT NULL,
    PRIMARY KEY (batch_id, row_number)
);
CREATE TABLE IF NOT EXISTS current_records (
    kind VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    revision BIGINT NOT NULL,
    variant_count BIGINT NOT NULL,
    occurrence_count BIGINT NOT NULL,
    payload JSON,
    PRIMARY KEY (kind, record_id)
);

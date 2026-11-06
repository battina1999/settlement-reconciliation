CREATE OR REPLACE VIEW ledger AS
SELECT record_id, revision,
       payload->>'merchant_id' AS merchant_id,
       payload->>'payment_id' AS payment_id,
       payload->>'currency' AS currency,
       (payload->>'business_date')::DATE AS business_date,
       (payload->>'gross_cents')::BIGINT AS gross_cents,
       (payload->>'fee_cents')::BIGINT AS fee_cents,
       (payload->>'gross_cents')::BIGINT - (payload->>'fee_cents')::BIGINT AS net_cents
FROM current_records WHERE kind = 'ledger' AND variant_count = 1;

CREATE OR REPLACE VIEW settlements AS
SELECT record_id, revision,
       payload->>'merchant_id' AS merchant_id,
       payload->>'payment_id' AS payment_id,
       payload->>'payout_id' AS payout_id,
       payload->>'currency' AS currency,
       (payload->>'business_date')::DATE AS business_date,
       (payload->>'gross_cents')::BIGINT AS gross_cents,
       (payload->>'fee_cents')::BIGINT AS fee_cents,
       (payload->>'gross_cents')::BIGINT - (payload->>'fee_cents')::BIGINT AS net_cents
FROM current_records WHERE kind = 'settlements' AND variant_count = 1;

CREATE OR REPLACE VIEW payouts AS
SELECT record_id, revision,
       payload->>'merchant_id' AS merchant_id,
       payload->>'payout_id' AS payout_id,
       payload->>'currency' AS currency,
       (payload->>'business_date')::DATE AS business_date,
       (payload->>'net_cents')::BIGINT AS net_cents
FROM current_records WHERE kind = 'payouts' AND variant_count = 1;

-- Count records before joining to keep a second settlement from multiplying
-- the ledger amount. Comparisons below use only one-to-one pairs.
CREATE OR REPLACE VIEW settlement_counts AS
SELECT merchant_id, payment_id, count(*) AS settlement_count
FROM settlements GROUP BY merchant_id, payment_id;

CREATE OR REPLACE VIEW matched_payments AS
SELECT l.merchant_id, l.payment_id, l.record_id AS ledger_record_id,
       s.record_id AS settlement_record_id, s.payout_id,
       l.currency AS ledger_currency, s.currency AS settlement_currency,
       l.gross_cents AS expected_gross, s.gross_cents AS observed_gross,
       l.fee_cents AS expected_fee, s.fee_cents AS observed_fee,
       l.net_cents AS expected_net, s.net_cents AS observed_net
FROM ledger l JOIN settlement_counts c USING (merchant_id, payment_id)
JOIN settlements s USING (merchant_id, payment_id)
WHERE c.settlement_count = 1;

CREATE OR REPLACE VIEW settlement_payout_totals AS
SELECT merchant_id, payout_id, currency, count(*) AS settlement_count,
       sum(net_cents)::BIGINT AS net_cents
FROM settlements GROUP BY merchant_id, payout_id, currency;

CREATE OR REPLACE TABLE currency_totals AS
WITH totals AS (
    SELECT currency, net_cents, 'ledger' AS source FROM ledger
    UNION ALL SELECT currency, net_cents, 'settlements' FROM settlements
    UNION ALL SELECT currency, net_cents, 'payouts' FROM payouts
)
SELECT currency,
       coalesce(sum(net_cents) FILTER (WHERE source = 'ledger'), 0)::BIGINT AS ledger_net_cents,
       coalesce(sum(net_cents) FILTER (WHERE source = 'settlements'), 0)::BIGINT AS settlement_net_cents,
       coalesce(sum(net_cents) FILTER (WHERE source = 'payouts'), 0)::BIGINT AS payout_net_cents,
       settlement_net_cents - ledger_net_cents AS settlement_variance_cents,
       payout_net_cents - settlement_net_cents AS payout_variance_cents
FROM totals GROUP BY currency ORDER BY currency;

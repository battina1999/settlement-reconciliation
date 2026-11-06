-- One issue can coexist with another issue for the same payment. The queue is
-- a collection of checks, not an additive financial balance.
CREATE OR REPLACE TABLE issues AS
WITH checks AS (
    SELECT 'source_conflict' AS issue_type, 'high' AS severity,
           kind, record_id AS entity_id,
           split_part(record_id, '/', 1) AS merchant_id, NULL::VARCHAR AS currency,
           NULL::BIGINT AS expected_cents, NULL::BIGINT AS observed_cents,
           'Different payloads at revision ' || revision || '. Resolve upstream with a higher revision.' AS reason
    FROM current_records WHERE variant_count > 1
    UNION ALL
    SELECT 'repeated_source_row', 'review', kind, record_id,
           payload->>'merchant_id', payload->>'currency', NULL, NULL,
           (occurrence_count - 1) || ' repeated row(s) at the active revision. Counted once.'
    FROM current_records WHERE variant_count = 1 AND occurrence_count > 1
    UNION ALL
    SELECT 'missing_settlement', 'high', 'ledger', l.record_id,
           l.merchant_id, l.currency, l.net_cents, NULL,
           'No unambiguous settlement line for this merchant and payment.'
    FROM ledger l LEFT JOIN settlement_counts c USING (merchant_id, payment_id)
    WHERE c.payment_id IS NULL
    UNION ALL
    SELECT 'multiple_settlements', 'high', 'ledger', l.record_id,
           l.merchant_id, l.currency, l.net_cents, NULL,
           c.settlement_count || ' distinct settlement IDs refer to the payment. Review each source line.'
    FROM ledger l JOIN settlement_counts c USING (merchant_id, payment_id)
    WHERE c.settlement_count > 1
    UNION ALL
    SELECT 'unexpected_settlement', 'high', 'settlements', s.record_id,
           s.merchant_id, s.currency, NULL, s.net_cents,
           'No unambiguous ledger payment for this merchant and payment.'
    FROM settlements s LEFT JOIN ledger l USING (merchant_id, payment_id)
    WHERE l.payment_id IS NULL
    UNION ALL
    SELECT 'payment_currency_mismatch', 'high', 'ledger', ledger_record_id,
           merchant_id, ledger_currency, expected_net, NULL,
           'Ledger currency ' || ledger_currency || ' differs from settlement currency ' || settlement_currency || '.'
    FROM matched_payments WHERE ledger_currency <> settlement_currency
    UNION ALL
    SELECT 'payment_amount_mismatch', 'high', 'ledger', ledger_record_id,
           merchant_id, ledger_currency, expected_net, observed_net,
           'Gross or fee differs. Ledger gross/fee ' || expected_gross || '/' || expected_fee ||
           ' cents; settlement gross/fee ' || observed_gross || '/' || observed_fee || ' cents.'
    FROM matched_payments
    WHERE ledger_currency = settlement_currency
      AND (expected_gross <> observed_gross OR expected_fee <> observed_fee)
    UNION ALL
    SELECT 'missing_payout', 'high', 'settlements', s.merchant_id || '/' || s.payout_id || '/' || s.currency,
           s.merchant_id, s.currency, s.net_cents, NULL,
           'Settlement lines refer to a payout absent from the unambiguous payout headers.'
    FROM settlement_payout_totals s LEFT JOIN payouts p USING (merchant_id, payout_id)
    WHERE p.payout_id IS NULL
    UNION ALL
    SELECT 'payout_currency_mismatch', 'high', 'payouts', p.record_id || '/' || s.currency,
           p.merchant_id, p.currency, NULL, p.net_cents,
           'Settlement group has currency ' || s.currency || ' and payout header has ' || p.currency || '.'
    FROM payouts p JOIN settlement_payout_totals s USING (merchant_id, payout_id)
    WHERE p.currency <> s.currency
    UNION ALL
    SELECT 'payout_amount_mismatch', 'high', 'payouts', p.record_id,
           p.merchant_id, p.currency, s.net_cents, p.net_cents,
           'Payout header net differs from the sum of clean settlement lines.'
    FROM payouts p JOIN settlement_payout_totals s USING (merchant_id, payout_id, currency)
    WHERE p.net_cents <> s.net_cents
    UNION ALL
    SELECT 'unexpected_payout', 'high', 'payouts', p.record_id,
           p.merchant_id, p.currency, NULL, p.net_cents,
           'No unambiguous settlement lines for this payout.'
    FROM payouts p LEFT JOIN settlement_payout_totals s USING (merchant_id, payout_id)
    WHERE s.payout_id IS NULL
)
SELECT md5(issue_type || ':' || kind || ':' || entity_id || ':' || coalesce(currency, '')) AS issue_id,
       *, CASE WHEN expected_cents IS NOT NULL AND observed_cents IS NOT NULL
               THEN observed_cents - expected_cents END AS variance_cents
FROM checks;

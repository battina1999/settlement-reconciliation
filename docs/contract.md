# Input contract

The CLI takes UTF-8 CSVs with a header. Column order may vary. Each file must contain exactly the columns for its source kind. Missing, duplicated or extra columns reject the file. A malformed row rejects the entire invocation before writing to the database, even if another file in that invocation is valid.

| Source | Required columns |
| --- | --- |
| Ledger | `merchant_id`, `payment_id`, `currency`, `business_date`, `gross_cents`, `fee_cents`, `revision` |
| Settlements | All ledger columns plus `settlement_id`, `payout_id` |
| Payouts | `merchant_id`, `payout_id`, `currency`, `business_date`, `net_cents`, `revision` |

IDs use 1–64 ASCII letters, digits, underscores or hyphens. Empty IDs and leading/trailing spaces are rejected. Business dates use `YYYY-MM-DD`. Supported currencies are `USD` and `EUR`, both with two decimal minor units. Revisions are integers from 1 through 2,147,483,647.

Amounts are nonnegative integer cents up to 1,000,000,000,000 per field. Decimal amounts, currency symbols and negative values are rejected. For purchase records, `fee_cents` must be no greater than `gross_cents`. Net is computed as gross minus fee. Payout net is supplied by the processor header. Totals use signed 64-bit storage, and an overflow rolls back the import. JSON reports serialize monetary totals as decimal strings so a browser can use exact integer arithmetic.

## Identity and revisions

Ledger identity is `(merchant_id, payment_id)`. Settlement identity is `(merchant_id, settlement_id)`. Payout identity is `(merchant_id, payout_id)`. The identity includes the merchant. Different merchants may reuse an external ID.

A source key has one current revision. The largest revision wins, regardless of file arrival order or business date. The complete canonical payload at that revision must agree across all occurrences. The canonical payload normalizes integers, so `000100` and `100` are the same amount. Identical rows are counted once. A disagreement in any payload field quarantines the source key until a higher revision arrives.

A file is recognized by its source kind and SHA-256 fingerprint. A byte-identical retry is skipped, even if its path changes. A changed file is appended as another batch. Exact source rows repeated across byte-different files still resolve to one current record, with their occurrences retained.

Omission from a later file does not delete a source key. This contract has no deletion or void event. A ledger payment must have at most one current settlement for a one-to-one match. Splits, retries with a different settlement ID, refunds and chargebacks require review or an extended source contract.

## Checks and balance rules

A clean payment match requires the same merchant and payment ID, exactly one settlement ID, matching currency, matching gross cents and matching fee cents. Matching never crosses currencies. Each distinct settlement ID is retained when multiple IDs reference a payment. That allows an analyst to see the actual settlement overstatement instead of silently discarding a source line.

Payout expectation is the sum of clean settlement net amounts by merchant, payout ID and currency, including settlement lines whose ledger payment is missing. A payout is a processor claim about its settlement lines. A ledger join would hide those lines from the payout check.

The issue table distinguishes conflicting source revisions, repeated rows, missing clean settlements, multiple settlements, unexpected settlements, payment currency or amount differences, missing clean payouts, unexpected payouts and payout currency or amount differences. A null expected or observed amount means that side is unavailable or cannot be compared in the same currency. A zero variance may still have a gross or fee discrepancy.

Clean source totals exclude quarantined keys. A conflict may therefore also create downstream missing-record or amount checks. Issue counts measure checks, and a source record can participate in several checks. Use `currency_totals` for financial balances and the issue queue for investigation.

## Operations

The importer validates complete files in memory and uses one writer transaction. It appends raw batches, resolves touched source keys and rebuilds report tables. The business date never determines which keys are eligible for correction. If a transformation fails, all changes from the invocation roll back. Retrying the same delivery is safe after fixing the error.

A second writer receives DuckDB's lock error. The command exits with the error and can be retried when the first writer finishes. This is a local single-writer application. It has no background scheduler, network ingestion, user authentication, bank integration or automatic settlement action.

Every issue export carries the relevant imported rows with source filename, batch ID and one-based data-row number. The CSV header is excluded from that row number. Conflicting versions and changed payment references remain visible in the drilldown.

## Files after a demo run

The generated CSVs are in `build/inputs/initial/` and `build/inputs/corrections/`. The database is `build/demo.duckdb`. `docs/data/demo.json` contains the initial and corrected reports and import audit counts. The demo recreates only its own database. The general CLI uses the supplied database path and preserves its history across calls.

# Settlement reconciliation

I built this to trace the difference between what a merchant expects to receive, what a processor says it settled, and what appears on a payout header. The review queue keeps the original file rows beside each discrepancy so an analyst can work out what needs correcting.

[Open the review workbench](https://battina1999.github.io/settlement-reconciliation/) · [Input contract](docs/contract.md) · [Reconciliation SQL](sql/04_issues.sql)

All demo records are synthetic. The generator creates 12,000 purchase payments across three merchants and two currencies, then adds specific errors and a later correction delivery.

## What the demo produces

| Check | Initial delivery | After late corrections |
| --- | ---: | ---: |
| Ledger payments | 12,000 | 12,015 |
| Clean settlement records | 11,951 | 12,023 |
| Conflicting source records quarantined | 12 | 0 |
| Open checks | 182 | 8 |
| Raw source rows retained | 24,125 | 24,392 |

The correction delivery adds 15 ledger payments that arrived after their settlement lines. It also repairs missing lines, amounts, currencies and conflicting revisions. Eight payments still have two distinct settlement IDs, so they stay in the queue. The remaining settlement-to-ledger differences are **9,599.05 EUR** and **11,585.09 USD**, separately. Payout totals agree with the settlement totals in each currency after the corrections. Those are measured results of the generated scenario.

Replaying all six files imports zero rows and produces the same report. The demo checks that equality before writing the dashboard data. [Generator](src/settlement_reconciliation/synthetic.py) · [Demo runner](scripts/run_demo.py) · [Published results](docs/data/demo.json)

## One discrepancy, from source row to correction

This is **independent portfolio work using synthetic records**. It does not contain employer, customer or processor data.

I use payment `M1/P000063` to show how the review queue explains a difference. Both source records have currency `USD` and business date `2026-01-11`. The settlement is `S000063`, under payout `OUT_M1_USD_20260111`.

| Source | Data row | Revision | Gross cents | Fee cents | Net cents |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial `ledger.csv` | 63 | 1 | 311717 | 9070 | 302647 |
| Initial `settlements.csv` | 3 | 1 | 311717 | 9207 | 302510 |
| Correction `settlements.csv` | 63 | 2 | 311717 | 9070 | 302647 |

Row numbers exclude the CSV header. Net is gross minus fee.

The initial settlement fee is 137 cents higher than the ledger fee. The queue opens `payment_amount_mismatch`: expected net **$3,026.47**, observed net **$3,025.10**, variance **−$1.37**. Its evidence includes both original rows.

This is the [amount-check condition](sql/04_issues.sql), narrowed to that payment:

```sql
SELECT merchant_id, payment_id, expected_net, observed_net,
       observed_net - expected_net AS variance_cents
FROM matched_payments
WHERE merchant_id = 'M1'
  AND payment_id = 'P000063'
  AND ledger_currency = settlement_currency
  AND (expected_gross <> observed_gross OR expected_fee <> observed_fee);
```

The later synthetic delivery keeps the same settlement ID and supplies revision 2 with the corrected fee. The higher revision becomes current; the original row stays in the source history. Both nets then equal 302647 cents, and this payment no longer appears in the corrected issue queue.

[Published before/after results](docs/data/demo.json) · [Correction generator](src/settlement_reconciliation/synthetic.py) · [Revision rules](docs/contract.md)

## Run it

With Python 3.10 or later installed, run this from the repository root.

```bash
make demo
make test
make serve
```

`make demo` creates a virtual environment, installs the pinned DuckDB dependency, generates the source CSVs, reconciles both deliveries and verifies the replay. `make serve` opens a local server at <http://localhost:8000>. The dashboard lets you switch deliveries, filter checks, inspect the original rows and download the filtered queue as CSV.

To reconcile other files that follow the contract, use the same engine directly.

```bash
PYTHONPATH=src .venv/bin/python -m settlement_reconciliation \
  --database build/my-reconciliation.duckdb \
  --ledger path/to/ledger.csv \
  --settlements path/to/settlements.csv \
  --payouts path/to/payouts.csv \
  --report build/my-report.json
```

Each source argument accepts multiple files. A later invocation can supply just the new delivery. Source files are append-only history. A changed record uses a higher revision. [Columns, supported values and correction rules](docs/contract.md)

## The decisions that matter

- **Money stays in integer cents.** SQL compares gross, fee and net separately. Equal net amounts can conceal different gross amounts and fees, so that still opens a check. USD and EUR are reconciled independently.
- **A conflict needs a correction.** Identical rows at the highest revision count once and remain visible as a duplicate-row review. Different payloads at that revision quarantine the source key. The pipeline keeps both payloads for investigation and accepts a higher revision as the resolution.
- **Late records use their IDs.** Ingestion resolves only the record keys touched by new files and examines their full revision history. A correction to an old business date reaches the current state. The SQL then rebuilds the report tables from that state in the same transaction.
- **An import either commits together or rolls back.** Raw rows, revision resolution and analytical results are one DuckDB transaction. File fingerprints make retries safe. Concurrent writes are rejected by DuckDB's writer lock and can be retried after the active writer exits.
- **The queue is a set of checks.** A quarantined settlement can also cause a missing-clean-settlement check and a payout difference. Summing issue amounts would double-count some problems. The currency balance table comes from the clean source models instead.

The current tradeoff is a complete rebuild of the issue and balance tables after incrementally resolving source records. That keeps old corrections and changed payout references easy to reason about at this scale. A larger deployment would need measured partitioning and concurrency requirements before changing that design.

## Checks I run

The tests cover cents, duplicate files and rows, out-of-order revisions, conflicting source IDs, changed payment references in the evidence view, currency mismatches, gross/fee differences that cancel out at net, multiple settlements, malformed inputs and transaction rollback after a transformation fails. CI also runs the full 12,000-payment demo and checks that the published JSON can be reproduced exactly. [Tests](tests/test_reconciliation.py) · [CI workflow](.github/workflows/ci.yml)

The inputs cover nonnegative purchase captures, gross amounts and fees in USD or EUR. Refunds, chargebacks, foreign exchange, bank statement matching and processor-specific file formats would require additional contracts and tests. The static dashboard uses the generated extract committed here. The CLI produces the same report shape for supplied files.

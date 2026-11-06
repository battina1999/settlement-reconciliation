"""Run with PYTHONPATH=src python -m settlement_reconciliation."""
import argparse
import json
from pathlib import Path

from .engine import apply_files, snapshot

parser = argparse.ArgumentParser(description='Reconcile versioned ledger, settlement and payout CSVs in one transaction.')
parser.add_argument('--database', type=Path, default=Path('build/reconciliation.duckdb'))
for kind in ('ledger', 'settlements', 'payouts'):
    parser.add_argument('--' + kind, type=Path, action='append', default=[], help='CSV path; may be supplied multiple times')
parser.add_argument('--report', type=Path, help='Write a JSON report after a successful reconciliation')
args = parser.parse_args()
files = [(kind, path) for kind in ('ledger', 'settlements', 'payouts') for path in getattr(args, kind)]
if not files:
    parser.error('provide at least one input file')
audit = apply_files(args.database, files)
report = snapshot(args.database, 'Supplied CSV files')
if args.report:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'ingestion': audit, 'counts': report['counts'], 'currency_totals': report['currencies']}, indent=2))

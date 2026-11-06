"""Build and verify the checked-in dashboard from deterministic synthetic inputs."""
import json
from pathlib import Path
from time import perf_counter

from settlement_reconciliation.engine import ROOT, apply_files, snapshot
from settlement_reconciliation.synthetic import generate

started = perf_counter()
build = ROOT / 'build'
build.mkdir(exist_ok=True)
database = build / 'demo.duckdb'
# This command owns its demo database. The general CLI uses the caller's path.
database.unlink(missing_ok=True)
files = generate(build / 'inputs')
initial_audit = apply_files(database, files['initial'])
initial = snapshot(database, 'Initial delivery')
correction_audit = apply_files(database, files['corrections'])
corrected = snapshot(database, 'After late corrections')
replay_audit = apply_files(database, files['initial'] + files['corrections'])
replayed = snapshot(database, 'After late corrections')
assert corrected == replayed, 'Replaying files changed the report'
assert replay_audit['rows_loaded'] == 0
assert corrected['counts']['issues'] == 8
assert {issue['issue_type'] for issue in corrected['issues']} == {'multiple_settlements'}
report = {
    'synthetic': True,
    'description': 'Deterministic synthetic purchase records. No customer or processor data.',
    'coverage': '2026-01-01 through 2026-01-20',
    'snapshots': [initial, corrected],
    'ingestion': [initial_audit, correction_audit, replay_audit],
    'replay_identical': True,
}
output = ROOT / 'docs' / 'data' / 'demo.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps({'initial': initial['counts'], 'corrected': corrected['counts'],
                  'matched_after_corrections': corrected['matched_payments'],
                  'quarantined_initial': initial['quarantined_records'],
                  'replay': replay_audit, 'currency_totals': corrected['currencies'],
                  'seconds': round(perf_counter() - started, 2)}, indent=2))

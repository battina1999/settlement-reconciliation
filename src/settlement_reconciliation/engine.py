"""CSV intake and transactional SQL reconciliation."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / 'sql'
PAYMENT_FIELDS = ('merchant_id', 'payment_id', 'currency', 'business_date', 'gross_cents', 'fee_cents', 'revision')
FIELDS = {
    'ledger': PAYMENT_FIELDS,
    'settlements': PAYMENT_FIELDS + ('settlement_id', 'payout_id'),
    'payouts': ('merchant_id', 'payout_id', 'currency', 'business_date', 'net_cents', 'revision'),
}
ID_PATTERN = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
MAX_CENTS = 1_000_000_000_000


def read_input(kind: str, path: Path) -> tuple[str, list[dict]]:
    """Validate a complete file before changing the database."""
    if kind not in FIELDS:
        raise ValueError(f'Unsupported source kind {kind!r}')
    content = path.read_bytes()
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(FIELDS[kind]):
        raise ValueError(f'{path.name}: required columns are {", ".join(FIELDS[kind])}')
    result = []
    for line, incoming in enumerate(reader, start=2):
        try:
            if None in incoming or any(value is None for value in incoming.values()):
                raise ValueError('row has the wrong number of fields')
            row = dict(incoming)
            for name, value in row.items():
                if name.endswith('_id') and not ID_PATTERN.fullmatch(value):
                    raise ValueError(f'{name} must contain 1–64 letters, digits, underscores or hyphens')
                if name.endswith('_cents') or name == 'revision':
                    if not re.fullmatch(r'[0-9]+', value):
                        raise ValueError(f'{name} must be a nonnegative integer')
                    row[name] = int(value)
                    bound = MAX_CENTS if name.endswith('_cents') else 2_147_483_647
                    if row[name] > bound:
                        raise ValueError(f'{name} exceeds {bound}')
            if row['revision'] < 1:
                raise ValueError('revision starts at 1')
            if row['currency'] not in ('USD', 'EUR'):
                raise ValueError('currency must be USD or EUR (two decimal minor units)')
            if date.fromisoformat(row['business_date']).isoformat() != row['business_date']:
                raise ValueError('business_date must be YYYY-MM-DD')
            if kind != 'payouts' and row['fee_cents'] > row['gross_cents']:
                raise ValueError('fee_cents exceeds gross_cents')
            key = {'ledger': 'payment_id', 'settlements': 'settlement_id', 'payouts': 'payout_id'}[kind]
            row_id = row['merchant_id'] + '/' + row[key]
            payload = json.dumps(row, sort_keys=True, separators=(',', ':'))
            result.append({'record_id': row_id, 'revision': row['revision'], 'payload': payload,
                           'payload_hash': hashlib.sha256(payload.encode()).hexdigest()})
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{path.name}, row {line}: {exc}') from exc
    return hashlib.sha256(content).hexdigest(), result


def apply_files(database: Path, files: list[tuple[str, Path]]) -> dict:
    """Commit raw history, current records and report tables together.

    A DuckDB writer lock makes concurrent writes fail without partial state.
    The caller can safely retry the whole command once the other writer exits.
    """
    parsed = [(kind, path, *read_input(kind, path)) for kind, path in files]
    database.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database))
    new_rows = 0
    added = 0
    skipped = 0
    try:
        con.execute('BEGIN TRANSACTION')
        con.execute((SQL / '01_schema.sql').read_text())
        con.execute('CREATE TEMP TABLE changed_keys (kind VARCHAR, record_id VARCHAR, PRIMARY KEY(kind, record_id))')
        for kind, path, fingerprint, records in parsed:
            present = con.execute('SELECT 1 FROM batches WHERE kind = ? AND sha256 = ?',
                                  [kind, fingerprint]).fetchone()
            if present:
                skipped += 1
                continue
            batch_id = con.execute('INSERT INTO batches(kind, sha256, filename, row_count) VALUES (?, ?, ?, ?) RETURNING batch_id',
                                   [kind, fingerprint, path.name, len(records)]).fetchone()[0]
            if records:
                rows = [(batch_id, index, kind, row['record_id'], row['revision'], row['payload'], row['payload_hash'])
                        for index, row in enumerate(records, start=1)]
                # Parameter binding keeps source IDs and file values out of SQL text.
                con.executemany('INSERT INTO raw_records VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
                con.execute('INSERT INTO changed_keys SELECT DISTINCT kind, record_id FROM raw_records WHERE batch_id = ? ON CONFLICT DO NOTHING', [batch_id])
            added += 1
            new_rows += len(records)
        affected = con.execute('SELECT count(*) FROM changed_keys').fetchone()[0]
        con.execute((SQL / '02_resolve.sql').read_text())
        con.execute((SQL / '03_models.sql').read_text())
        con.execute((SQL / '04_issues.sql').read_text())
        con.execute('COMMIT')
        return {'files_loaded': added, 'files_replayed': skipped, 'rows_loaded': new_rows, 'keys_reconsidered': affected}
    except Exception:
        con.execute('ROLLBACK')
        raise
    finally:
        con.close()


def _dicts(con: duckdb.DuckDBPyConnection, query: str) -> list[dict]:
    cursor = con.execute(query)
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    for row in rows:
        for key, value in row.items():
            if key.endswith('_cents') and value is not None:
                row[key] = str(value)  # JavaScript BigInt reads amounts without rounding.
    return rows


def snapshot(database: Path, label: str) -> dict:
    con = duckdb.connect(str(database), read_only=True)
    try:
        result = {
            'label': label,
            'counts': {name: con.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                       for name in ('batches', 'raw_records', 'current_records', 'ledger', 'settlements', 'payouts', 'issues')},
            'quarantined_records': con.execute('SELECT count(*) FROM current_records WHERE variant_count > 1').fetchone()[0],
            'matched_payments': con.execute('SELECT count(*) FROM matched_payments WHERE ledger_currency = settlement_currency AND expected_gross = observed_gross AND expected_fee = observed_fee').fetchone()[0],
            'currencies': _dicts(con, 'SELECT * FROM currency_totals ORDER BY currency'),
            'issues': _dicts(con, 'SELECT * FROM issues ORDER BY severity, issue_type, entity_id, currency'),
            'batches': _dicts(con, 'SELECT * FROM batches ORDER BY batch_id'),
        }
        # Keep full versions for each reviewed record and its related payment.
        # Payout drilldown shows its header and aggregate amount in the issue.
        source_rows = _dicts(con, 'SELECT r.kind, r.record_id, r.revision, r.batch_id, r.row_number, r.payload, b.filename FROM raw_records r JOIN batches b USING(batch_id) ORDER BY r.kind, r.record_id, r.revision, r.batch_id, r.row_number')
        by_key = {}
        by_payment = {}
        by_payout = {}
        for row in source_rows:
            row['payload'] = json.loads(row['payload'])
            by_key.setdefault((row['kind'], row['record_id']), []).append(row)
            payload = row['payload']
            if row['kind'] in ('settlements', 'payouts'):
                by_payout.setdefault((payload['merchant_id'], payload['payout_id']), []).append(row)
            if row['kind'] in ('ledger', 'settlements'):
                by_payment.setdefault((payload['merchant_id'], payload['payment_id']), []).append(row)
        for issue in result['issues']:
            entity_key = '/'.join(issue['entity_id'].split('/')[:2])
            records = by_key.get((issue['kind'], entity_key), [])
            if issue['kind'] == 'payouts' or issue['issue_type'] == 'missing_payout':
                merchant, payout = entity_key.split('/')
                records = by_payout.get((merchant, payout), records)
            if records and issue['kind'] in ('ledger', 'settlements') and issue['issue_type'] != 'missing_payout':
                payment_keys = {(row['payload']['merchant_id'], row['payload']['payment_id']) for row in records}
                related = [row for key in sorted(payment_keys) for row in by_payment[key]]
                records = list({(row['batch_id'], row['row_number']): row for row in records + related}.values())
            issue['source_records'] = records
        return result
    finally:
        con.close()

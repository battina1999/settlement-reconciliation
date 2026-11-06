import duckdb
import pytest

from settlement_reconciliation import engine
from settlement_reconciliation.engine import apply_files, snapshot
from settlement_reconciliation.synthetic import write_csv


@pytest.fixture
def payment():
    return {'merchant_id': 'M1', 'payment_id': 'P1', 'currency': 'USD',
            'business_date': '2025-01-01', 'gross_cents': 10001, 'fee_cents': 321, 'revision': 1}


def settlement(payment, **changes):
    return {**payment, 'settlement_id': 'S1', 'payout_id': 'OUT1', **changes}


def ingest(tmp_path, kind, rows, name='file.csv'):
    return kind, write_csv(tmp_path / name, kind, rows)


def issue_types(database):
    return {row['issue_type'] for row in snapshot(database, '')['issues']}


def test_integer_money_and_matching(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    payout = {'merchant_id': 'M1', 'payout_id': 'OUT1', 'currency': 'USD',
              'business_date': '2025-01-02', 'net_cents': 9680, 'revision': 1}
    apply_files(db, [ingest(tmp_path, 'ledger', [payment], 'ledger.csv'),
                     ingest(tmp_path, 'settlements', [settlement(payment)], 'settlements.csv'),
                     ingest(tmp_path, 'payouts', [payout], 'payouts.csv')])
    report = snapshot(db, '')
    assert report['matched_payments'] == 1
    assert report['counts']['issues'] == 0
    assert report['currencies'][0] == {'currency': 'USD', 'ledger_net_cents': '9680',
                                      'settlement_net_cents': '9680', 'payout_net_cents': '9680',
                                      'settlement_variance_cents': '0', 'payout_variance_cents': '0'}


def test_file_replay_and_duplicate_rows_preserve_amounts(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    source = ingest(tmp_path, 'ledger', [payment, payment])
    apply_files(db, [source])
    before = snapshot(db, '')
    replay = apply_files(db, [source])
    assert replay == {'files_loaded': 0, 'files_replayed': 1, 'rows_loaded': 0, 'keys_reconsidered': 0}
    assert snapshot(db, '') == before
    assert before['currencies'][0]['ledger_net_cents'] == '9680'
    assert 'repeated_source_row' in issue_types(db)
    # A byte-different file with the same row is also deduplicated by record/revision.
    apply_files(db, [ingest(tmp_path, 'ledger', [payment], 'retry.csv')])
    assert snapshot(db, '')['currencies'][0]['ledger_net_cents'] == '9680'


def test_late_and_out_of_order_revision(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    apply_files(db, [ingest(tmp_path, 'ledger', [payment])])
    correction = {**payment, 'gross_cents': 10101, 'revision': 3}
    apply_files(db, [ingest(tmp_path, 'ledger', [correction], 'late.csv')])
    apply_files(db, [ingest(tmp_path, 'ledger', [{**payment, 'gross_cents': 5000, 'revision': 2}], 'older.csv')])
    result = snapshot(db, '')
    assert result['currencies'][0]['ledger_net_cents'] == '9780'
    assert result['quarantined_records'] == 0


def test_conflict_quarantines_then_higher_revision_resolves(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    files = [ingest(tmp_path, 'ledger', [payment, {**payment, 'gross_cents': 10002}])]
    apply_files(db, files)
    before = snapshot(db, '')
    assert before['quarantined_records'] == 1
    assert before['counts']['ledger'] == 0
    assert issue_types(db) == {'source_conflict'}
    apply_files(db, [ingest(tmp_path, 'ledger', [{**payment, 'revision': 2}], 'fix.csv')])
    assert snapshot(db, '')['counts']['ledger'] == 1
    assert 'source_conflict' not in issue_types(db)


def test_conflict_drilldown_includes_changed_payment_ids(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    sources = [settlement(payment), settlement(payment, revision=2, payment_id='P2'),
               settlement(payment, revision=2, payment_id='P3')]
    apply_files(db, [ingest(tmp_path, 'ledger', [payment]),
                     ingest(tmp_path, 'settlements', sources, 'settlements.csv')])
    issue = next(row for row in snapshot(db, '')['issues'] if row['issue_type'] == 'source_conflict')
    evidence = [row for row in issue['source_records'] if row['kind'] == 'settlements']
    assert {(row['revision'], row['payload']['payment_id']) for row in evidence} == {(1, 'P1'), (2, 'P2'), (2, 'P3')}


def test_currency_mismatch_is_not_a_money_difference(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    apply_files(db, [ingest(tmp_path, 'ledger', [payment]),
                     ingest(tmp_path, 'settlements', [settlement(payment, currency='EUR')], 'settlements.csv')])
    result = snapshot(db, '')
    mismatch = next(row for row in result['issues'] if row['issue_type'] == 'payment_currency_mismatch')
    assert mismatch['variance_cents'] is None
    assert {row['currency'] for row in result['currencies']} == {'USD', 'EUR'}
    assert result['matched_payments'] == 0


def test_same_net_different_gross_fee_still_requires_review(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    apply_files(db, [ingest(tmp_path, 'ledger', [payment]),
                     ingest(tmp_path, 'settlements', [settlement(payment, gross_cents=10101, fee_cents=421)], 'settlements.csv')])
    issue = next(row for row in snapshot(db, '')['issues'] if row['issue_type'] == 'payment_amount_mismatch')
    assert issue['variance_cents'] == '0'


def test_multiple_settlements_do_not_multiply_the_ledger(payment, tmp_path):
    db = tmp_path / 'a.duckdb'
    apply_files(db, [ingest(tmp_path, 'ledger', [payment]),
                     ingest(tmp_path, 'settlements', [settlement(payment), settlement(payment, settlement_id='S2')], 'settlements.csv')])
    result = snapshot(db, '')
    assert result['currencies'][0]['ledger_net_cents'] == '9680'
    assert result['currencies'][0]['settlement_net_cents'] == '19360'
    assert 'multiple_settlements' in issue_types(db)
    assert result['matched_payments'] == 0


@pytest.mark.parametrize('changes', [
    {'gross_cents': '10.01'}, {'fee_cents': -1}, {'revision': 0},
    {'currency': 'JPY'}, {'business_date': '2025-99-99'}, {'merchant_id': '../bad'},
    {'gross_cents': engine.MAX_CENTS + 1}, {'fee_cents': 10002},
])
def test_invalid_file_rejects_entire_invocation(payment, tmp_path, changes):
    db = tmp_path / 'a.duckdb'
    valid = ingest(tmp_path, 'ledger', [payment], 'valid.csv')
    invalid = ingest(tmp_path, 'ledger', [{**payment, **changes}], 'invalid.csv')
    with pytest.raises(ValueError):
        apply_files(db, [valid, invalid])
    assert not db.exists()


def test_transform_failure_rolls_back_intake_and_report(payment, tmp_path, monkeypatch):
    db = tmp_path / 'a.duckdb'
    apply_files(db, [ingest(tmp_path, 'ledger', [payment])])
    before = snapshot(db, '')
    broken_sql = tmp_path / 'sql'
    broken_sql.mkdir()
    for path in engine.SQL.glob('*.sql'):
        (broken_sql / path.name).write_text(path.read_text())
    (broken_sql / '04_issues.sql').write_text('SELECT * FROM deliberately_missing_table')
    monkeypatch.setattr(engine, 'SQL', broken_sql)
    with pytest.raises(duckdb.Error):
        apply_files(db, [ingest(tmp_path, 'ledger', [{**payment, 'revision': 2}], 'fix.csv')])
    assert snapshot(db, '') == before

"""Deterministic purchase-only records and deliberately injected discrepancies."""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from .engine import FIELDS


def write_csv(path: Path, kind: str, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS[kind], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    return path


def generate(directory: Path) -> dict:
    rng = random.Random(412)
    ledger = []
    clean = []
    for index in range(1, 12_001):
        merchant = f'M{index % 3 + 1}'
        currency = 'USD' if index % 2 else 'EUR'
        day = date(2026, 1, 1) + timedelta(days=(index // 6) % 20)
        gross = rng.randint(1500, 500_000)
        payment = {'merchant_id': merchant, 'payment_id': f'P{index:06}', 'currency': currency,
                   'business_date': day.isoformat(), 'gross_cents': gross,
                   'fee_cents': (gross * 29 + 500) // 1000 + 30, 'revision': 1}
        ledger.append(payment)
        clean.append({**payment, 'settlement_id': f'S{index:06}',
                      'payout_id': f'OUT_{merchant}_{currency}_{day:%Y%m%d}'})

    original = deepcopy(clean)
    corrections = []
    base = []
    for index, row in enumerate(clean, start=1):
        if index <= 60:
            corrections.append(deepcopy(row))
            continue
        if 61 <= index <= 84:
            corrections.append({**original[index - 1], 'revision': 2})
            row['fee_cents'] += 137
        if 85 <= index <= 96:
            corrections.append({**row, 'revision': 2})
            base.append({**row, 'gross_cents': row['gross_cents'] + 101})
        if 97 <= index <= 126:
            corrections.append({**row, 'revision': 2})
            base.append(deepcopy(row))
        if 127 <= index <= 134:
            base.append({**row, 'settlement_id': row['settlement_id'] + '_EXTRA'})
        if 135 <= index <= 140:
            corrections.append({**original[index - 1], 'revision': 2})
            row['currency'] = 'EUR' if row['currency'] == 'USD' else 'USD'
            row['payout_id'] = f"OUT_{row['merchant_id']}_{row['currency']}_{row['business_date'].replace('-', '')}"
        base.append(deepcopy(row))

    orphan_ledger = []
    for index in range(1, 16):
        payment = {'merchant_id': f'M{index % 3 + 1}', 'payment_id': f'LATE{index:03}',
                   'currency': 'USD' if index % 2 else 'EUR', 'business_date': '2026-01-05',
                   'gross_cents': 8999, 'fee_cents': 291, 'revision': 1}
        orphan_ledger.append(payment)
        base.append({**payment, 'settlement_id': f'S_LATE{index:03}',
                     'payout_id': f"OUT_{payment['merchant_id']}_{payment['currency']}_20260105"})

    def payout_rows(settlements: list[dict], revision: int) -> list[dict]:
        totals = defaultdict(int)
        # The source publisher's intended records choose the last duplicate ID.
        # Conflicting payloads remain in the files so the consumer must quarantine.
        latest = {row['settlement_id']: row for row in settlements}
        for row in latest.values():
            key = row['merchant_id'], row['payout_id'], row['currency'], row['business_date']
            totals[key] += row['gross_cents'] - row['fee_cents']
        return [{'merchant_id': merchant, 'payout_id': payout, 'currency': currency,
                 'business_date': day, 'net_cents': net, 'revision': revision}
                for (merchant, payout, currency, day), net in sorted(totals.items())]

    payouts = payout_rows(base, 1)
    for row in payouts[:3]:
        row['net_cents'] += 500
    final_settlements = {row['settlement_id']: row for row in base}
    final_settlements.update({row['settlement_id']: row for row in corrections})
    corrected_payouts = payout_rows(list(final_settlements.values()), 2)
    files = {}
    for phase, rows in [('initial', {'ledger': ledger, 'settlements': base, 'payouts': payouts}),
                        ('corrections', {'ledger': orphan_ledger, 'settlements': corrections, 'payouts': corrected_payouts})]:
        files[phase] = [(kind, write_csv(directory / phase / f'{kind}.csv', kind, data))
                        for kind, data in rows.items()]
    return files

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class ExpenseEntry:
    payer: str
    amount: float
    split_with: list[str]


def parse_split_members(raw_members: str, payer: str) -> list[str]:
    members = [m.strip() for m in raw_members.split(";") if m.strip()]
    if payer not in members:
        members.append(payer)
    return members


def load_expenses(csv_path: Path) -> list[ExpenseEntry]:
    entries: list[ExpenseEntry] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            payer = (row.get("payer") or "").strip()
            amount = float((row.get("amount") or "").strip())
            split_with = parse_split_members(row.get("split_with") or "", payer)
            entries.append(ExpenseEntry(payer=payer, amount=amount, split_with=split_with))
    return entries


def compute_net_balances(entries: Iterable[ExpenseEntry]) -> dict[str, float]:
    balances: dict[str, float] = {}
    for entry in entries:
        share = entry.amount / len(entry.split_with)
        balances[entry.payer] = balances.get(entry.payer, 0.0) + entry.amount
        for person in entry.split_with:
            balances[person] = balances.get(person, 0.0) - share
    return balances


def settle_debts(balances: dict[str, float]) -> list[dict[str, object]]:
    debtors = sorted(
        ((person, amt) for person, amt in balances.items() if amt < 0),
        key=lambda item: item[1],
    )
    creditors = sorted(
        ((person, amt) for person, amt in balances.items() if amt > 0),
        key=lambda item: item[1],
        reverse=True,
    )

    settlements: list[dict[str, object]] = []
    i = 0
    j = 0
    debtor_vals = [[p, abs(a)] for p, a in debtors]
    creditor_vals = [[p, a] for p, a in creditors]

    while i < len(debtor_vals) and j < len(creditor_vals):
        debtor_name, owe_amt = debtor_vals[i]
        creditor_name, recv_amt = creditor_vals[j]
        transfer = min(owe_amt, recv_amt)
        settlements.append(
            {
                "from": creditor_name,
                "to": debtor_name,
                "amount": transfer,
            }
        )
        debtor_vals[i][1] -= transfer
        creditor_vals[j][1] -= transfer
        if debtor_vals[i][1] == 0:
            i += 1
        if creditor_vals[j][1] == 0:
            j += 1

    return settlements


def export_summary(csv_path: Path, out_path: Path) -> dict[str, object]:
    entries = load_expenses(csv_path)
    balances = compute_net_balances(entries)
    settlements = settle_debts(balances)
    payload = {
        "entry_count": len(entries),
        "balances": balances,
        "settlements": settlements,
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return payload

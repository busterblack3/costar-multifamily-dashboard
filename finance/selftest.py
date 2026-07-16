"""Offline end-to-end self-check. Run: ``python -m finance.selftest``.

Exercises the full pipeline (parse → store → categorize → report → dashboard)
against synthetic and fixture data, with no network access. Exits non-zero on
failure so it can be used in CI.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from . import categorize, dashboard, demodata, report
from .money import to_cents
from .simplefin import AccountSet, decode_setup_token
from .store import Store

FIXTURE = Path(__file__).with_name("fixtures") / "demo_accounts.json"


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run() -> int:
    # money conversion
    _check(to_cents("-42.19") == -4219, "to_cents negative decimal")
    _check(to_cents("3200.00") == 320000, "to_cents whole")
    _check(to_cents("") == 0, "to_cents empty")

    # setup-token decoding (DEMO token decodes to the claim URL)
    url = decode_setup_token(
        "aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1P"
    )
    _check(url.endswith("/simplefin/claim/DEMO"), f"token decode: {url}")

    # fixture parses into the model
    fx = AccountSet.from_json(json.loads(FIXTURE.read_text()))
    _check(len(fx.accounts) == 2, "fixture account count")
    _check(any(t.pending for a in fx.accounts for t in a.transactions), "fixture pending flag")

    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / ".finance")
        categorize.seed_default_rules(store)
        _check(store.rule_count() > 0, "rules seeded")

        # ingest synthetic data + categorize
        acctset = AccountSet.from_json(demodata.generate())
        counts = store.ingest(acctset.accounts)
        _check(counts["new"] > 0 and counts["new"] == counts["transactions"], "all new on first ingest")
        cat = categorize.categorize_all(store)
        _check(cat["matched"] > 0, "some transactions matched rules")

        # re-ingest is idempotent (no new rows)
        counts2 = store.ingest(acctset.accounts)
        _check(counts2["new"] == 0, "re-ingest inserts nothing new")

        # manual category is sticky across re-categorize
        row = store.transactions(limit=1)[0]
        store.set_category(row["account_id"], row["txn_id"], "MANUAL_TEST", manual=True)
        categorize.categorize_all(store, rerun=True)
        again = [
            r for r in store.transactions()
            if r["account_id"] == row["account_id"] and r["txn_id"] == row["txn_id"]
        ][0]
        _check(again["category"] == "MANUAL_TEST", "manual category preserved")

        # reports
        trend = report.monthly_trend(store, months=6)
        _check(len(trend) == 6, "trend length")
        _check(any(t["income_cents"] > 0 for t in trend), "trend has income")
        _check(any(t["spending_cents"] > 0 for t in trend), "trend has spending")

        # transfers excluded from spending
        by_cat = {d["category"] for d in trend and report.spending_by_category(store)}
        _check("Transfer" not in by_cat, "transfers excluded from spending")

        # budgets
        store.set_budget("Dining", 30000)
        b = report.budget_status(store)
        _check(any(r["category"] == "Dining" for r in b["rows"]), "budget row present")

        # dashboard renders self-contained HTML
        out = Path(d) / "dash.html"
        dashboard.build(store, out)
        html = out.read_text()
        _check(html.lstrip().startswith("<!doctype html>"), "dashboard is html")
        for needle in ('src="http', "src='http", 'href="http', "href='http", "//cdn", "unpkg", "jsdelivr"):
            _check(needle not in html, f"dashboard references external resource: {needle}")
        _check("Finance Dashboard" in html, "dashboard title present")

    print("selftest OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except AssertionError as e:
        print(f"selftest FAILED: {e}", file=sys.stderr)
        sys.exit(1)

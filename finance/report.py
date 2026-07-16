"""Aggregations: spending by category, monthly trends, budget vs actual.

Conventions:
- Spending is money *out* (negative amount_cents); reported as positive cents.
- Income is money *in* (positive amount_cents).
- The ``Transfer`` category is excluded from spending, income, and budgets so
  moving money between your own accounts isn't miscounted.
- Pending transactions are excluded from totals by default (they can move).
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Optional

from .categorize import UNCATEGORIZED
from .store import TRANSFER_CATEGORY, Store

EXCLUDED_FROM_SPENDING = {TRANSFER_CATEGORY, "Income"}


# ---------------------------------------------------------------------------
# Date helpers (epoch seconds, UTC)
# ---------------------------------------------------------------------------
def month_bounds(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp())


def parse_month(s: str) -> tuple[int, int]:
    """'2026-07' -> (2026, 7)."""
    year, month = s.split("-")
    return int(year), int(month)


def parse_date(s: str) -> int:
    """'YYYY-MM-DD' -> epoch seconds (UTC midnight)."""
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def month_label(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------
def spending_by_category(
    store: Store,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    account_id: Optional[str] = None,
) -> list[dict]:
    """Total spend per category (outflows only), largest first."""
    rows = store.transactions(
        start=start, end=end, account_id=account_id, include_pending=False
    )
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for r in rows:
        cat = r["category"] or UNCATEGORIZED
        if cat in EXCLUDED_FROM_SPENDING:
            continue
        if r["amount_cents"] >= 0:
            continue  # inflow, not spending
        totals[cat] = totals.get(cat, 0) + (-r["amount_cents"])
        counts[cat] = counts.get(cat, 0) + 1
    out = [
        {"category": c, "spent_cents": v, "count": counts[c]}
        for c, v in totals.items()
    ]
    out.sort(key=lambda d: d["spent_cents"], reverse=True)
    return out


def summarize(
    store: Store,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    account_id: Optional[str] = None,
) -> dict:
    """Headline numbers for a period: income, spending, net, top categories."""
    rows = store.transactions(
        start=start, end=end, account_id=account_id, include_pending=False
    )
    income = spend = 0
    for r in rows:
        cat = r["category"] or UNCATEGORIZED
        if cat == TRANSFER_CATEGORY:
            continue
        if r["amount_cents"] >= 0:
            income += r["amount_cents"]
        else:
            spend += -r["amount_cents"]
    return {
        "income_cents": income,
        "spending_cents": spend,
        "net_cents": income - spend,
        "by_category": spending_by_category(
            store, start=start, end=end, account_id=account_id
        ),
        "txn_count": len(rows),
    }


def monthly_trend(store: Store, *, months: int = 12) -> list[dict]:
    """Per-month income & spending for the last ``months`` calendar months."""
    now = datetime.now(timezone.utc)
    series = []
    y, m = now.year, now.month
    # walk backwards, then reverse to chronological order
    pairs = []
    for _ in range(months):
        pairs.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    for (yy, mm) in reversed(pairs):
        start, end = month_bounds(yy, mm)
        s = summarize(store, start=start, end=end)
        series.append(
            {
                "month": f"{yy:04d}-{mm:02d}",
                "income_cents": s["income_cents"],
                "spending_cents": s["spending_cents"],
                "net_cents": s["net_cents"],
            }
        )
    return series


def budget_status(
    store: Store, *, year: Optional[int] = None, month: Optional[int] = None
) -> dict:
    """Budget vs actual spending for a month.

    Prorates nothing — compares full monthly budget to spend so far in the
    given month (defaults to the current month).
    """
    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month
    start, end = month_bounds(year, month)
    spend = {
        d["category"]: d["spent_cents"]
        for d in spending_by_category(store, start=start, end=end)
    }
    budgets = store.budgets()
    rows = []
    for cat, budget_cents in sorted(budgets.items()):
        actual = spend.get(cat, 0)
        rows.append(
            {
                "category": cat,
                "budget_cents": budget_cents,
                "actual_cents": actual,
                "remaining_cents": budget_cents - actual,
                "pct": (actual / budget_cents) if budget_cents else 0.0,
            }
        )
    # categories with spend but no budget
    unbudgeted = [
        {"category": c, "spent_cents": v}
        for c, v in spend.items()
        if c not in budgets
    ]
    unbudgeted.sort(key=lambda d: d["spent_cents"], reverse=True)
    total_budget = sum(b for b in budgets.values())
    total_actual = sum(r["actual_cents"] for r in rows)
    return {
        "year": year,
        "month": month,
        "label": f"{year:04d}-{month:02d}",
        "rows": rows,
        "unbudgeted": unbudgeted,
        "total_budget_cents": total_budget,
        "total_actual_cents": total_actual,
        "days_in_month": calendar.monthrange(year, month)[1],
    }

"""Rule-based transaction categorization.

Rules match (case-insensitively) against a transaction's payee and/or
description. The highest-``priority`` matching rule wins. Manual categories
set during review are *sticky*: they are never overwritten by re-running
categorization or by a later sync.

The special ``Transfer`` category marks money movements between your own
accounts (and card payments); reports exclude it so it isn't counted as
spending or income.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .store import Store

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.default.json")
UNCATEGORIZED = "Uncategorized"


def load_default_rules() -> list[dict]:
    try:
        return json.loads(DEFAULT_RULES_PATH.read_text())
    except Exception:  # noqa: BLE001
        return []


def seed_default_rules(store: Store) -> int:
    """Populate the rules table with defaults if it's empty. Returns count added."""
    if store.rule_count() > 0:
        return 0
    added = 0
    for r in load_default_rules():
        store.add_rule(
            r["pattern"],
            r["category"],
            field=r.get("field", "both"),
            is_regex=bool(r.get("is_regex", False)),
            priority=int(r.get("priority", 100)),
        )
        added += 1
    return added


def _compile(rule) -> Optional[re.Pattern]:
    pattern = rule["pattern"]
    if rule["is_regex"]:
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None
    return re.compile(re.escape(pattern), re.IGNORECASE)


def _haystack(rule_field: str, payee: str, description: str) -> str:
    payee = payee or ""
    description = description or ""
    if rule_field == "payee":
        return payee
    if rule_field == "description":
        return description
    return f"{payee} {description}"


def match_category(rules, payee: str, description: str) -> Optional[str]:
    """Return the category of the highest-priority matching rule, or None.

    ``rules`` must already be ordered by priority DESC (as ``Store.rules``
    returns them).
    """
    for rule in rules:
        rx = _compile(rule)
        if rx is None:
            continue
        if rx.search(_haystack(rule["field"], payee, description)):
            return rule["category"]
    return None


def categorize_all(store: Store, *, rerun: bool = False) -> dict:
    """Apply rules to transactions.

    - By default only auto-categorizes rows that are not manually set and are
      currently uncategorized.
    - With ``rerun=True``, re-evaluates every non-manual row (useful after
      editing rules), leaving manual categories untouched.
    Returns counts of what changed.
    """
    rules = store.rules()
    rows = store.transactions(limit=None)
    changed = 0
    matched = 0
    for row in rows:
        if row["manual_category"]:
            continue
        current = row["category"]
        if not rerun and current:
            continue
        cat = match_category(rules, row["payee"], row["description"])
        new_cat = cat or UNCATEGORIZED
        if cat:
            matched += 1
        if new_cat != (current or ""):
            store.set_category(row["account_id"], row["txn_id"], new_cat, manual=False)
            changed += 1
    return {"scanned": len(rows), "changed": changed, "matched": matched}

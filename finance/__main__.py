"""Command-line interface for the SimpleFIN finance tracker.

Run ``python -m finance --help`` for the full command list. Typical flow:

    python -m finance init --token <SETUP_TOKEN>   # one time
    python -m finance sync                          # pull latest data
    python -m finance spending --month 2026-07
    python -m finance budget set Dining 300
    python -m finance dashboard --open

Everything is stored under ``.finance/`` (git-ignored). No data leaves your
machine except the read-only request to SimpleFIN during ``sync``.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import categorize, dashboard, demodata, report
from .money import dollars, plain
from .simplefin import (
    AccountSet,
    SimpleFinError,
    claim_setup_token,
    fetch_accounts,
)
from .store import DEFAULT_DIR, Store


# ---------------------------------------------------------------------------
# small presentation helpers
# ---------------------------------------------------------------------------
def _table(headers, rows, aligns=None) -> str:
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    aligns = aligns or ["<"] * len(headers)

    def fmt_row(cells):
        return "  ".join(
            f"{str(c):{a}{w}}" for c, w, a in zip(cells, widths, aligns)
        )

    out = [fmt_row(headers), "  ".join("-" * w for w in widths)]
    out += [fmt_row(r) for r in rows]
    return "\n".join(out)


def _resolve_period(args) -> tuple[int | None, int | None, str]:
    if getattr(args, "month", None):
        y, m = report.parse_month(args.month)
        s, e = report.month_bounds(y, m)
        return s, e, args.month
    if getattr(args, "from_", None) or getattr(args, "to", None):
        s = report.parse_date(args.from_) if args.from_ else None
        e = report.parse_date(args.to) if args.to else None
        return s, e, f"{args.from_ or '…'} → {args.to or '…'}"
    now = datetime.now(timezone.utc)
    s, e = report.month_bounds(now.year, now.month)
    return s, e, f"{now.year:04d}-{now.month:02d} (current month)"


def _store(args) -> Store:
    return Store(getattr(args, "dir", None) or DEFAULT_DIR)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    store = _store(args)
    categorize.seed_default_rules(store)
    if args.access_url:
        access_url = args.access_url.strip()
    elif args.token:
        print("Claiming setup token…")
        try:
            access_url = claim_setup_token(args.token)
        except SimpleFinError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    else:
        print("Provide --token <SETUP_TOKEN> or --access-url <URL>.", file=sys.stderr)
        print("Get a setup token from your SimpleFIN Bridge account.", file=sys.stderr)
        return 2
    store.save_access_url(access_url)
    print(f"Saved access URL to {store.config_path}")
    print("Rules seeded. Next: python -m finance sync")
    return 0


def _load_accounts(args, store: Store) -> AccountSet:
    if args.demo:
        return AccountSet.from_json(demodata.generate())
    access_url = store.get_access_url()
    if not access_url:
        raise SimpleFinError(
            "No access URL. Run `init` first, or set SIMPLEFIN_ACCESS_URL, "
            "or pass --demo to use synthetic data."
        )
    start = None
    if args.start:
        start = report.parse_date(args.start)
    elif args.days:
        start = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp())
    return fetch_accounts(access_url, start_date=start, pending=args.pending)


def cmd_sync(args) -> int:
    store = _store(args)
    categorize.seed_default_rules(store)
    try:
        acctset = _load_accounts(args, store)
    except SimpleFinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for err in acctset.errors:
        print(f"warning (SimpleFIN): {err}", file=sys.stderr)
    counts = store.ingest(acctset.accounts)
    cat = categorize.categorize_all(store)
    store.set_meta("last_sync", datetime.now(timezone.utc).isoformat())
    print(
        f"Synced {counts['accounts']} accounts, {counts['transactions']} transactions "
        f"({counts['new']} new). Auto-categorized {cat['changed']}."
    )
    return 0


def cmd_demo(args) -> int:
    args.demo = True
    args.start = args.days = None
    args.pending = False
    return cmd_sync(args)


def cmd_accounts(args) -> int:
    store = _store(args)
    rows = store.accounts()
    if not rows:
        print("No accounts. Run `sync` (or `demo`).")
        return 0
    table = _table(
        ["Account", "Institution", "Balance", "Available"],
        [
            [
                r["name"],
                r["org"] or "",
                dollars(r["balance_cents"]),
                dollars(r["available_cents"]) if r["available_cents"] is not None else "—",
            ]
            for r in rows
        ],
        aligns=["<", "<", ">", ">"],
    )
    total = sum((r["balance_cents"] or 0) for r in rows)
    print(table)
    print(f"\nTotal balance: {dollars(total)}")
    return 0


def cmd_spending(args) -> int:
    store = _store(args)
    start, end, label = _resolve_period(args)
    s = report.summarize(store, start=start, end=end, account_id=args.account)
    print(f"Spending — {label}\n")
    if not s["by_category"]:
        print("No spending in this period.")
    else:
        rows = [
            [d["category"], plain(d["spent_cents"]), str(d["count"])]
            for d in s["by_category"]
        ]
        print(_table(["Category", "Spent", "Txns"], rows, aligns=["<", ">", ">"]))
    print(
        f"\nIncome {dollars(s['income_cents'])}   "
        f"Spending {dollars(-s['spending_cents'])}   "
        f"Net {dollars(s['net_cents'])}"
    )
    return 0


def cmd_budget(args) -> int:
    store = _store(args)
    if args.budget_cmd == "set":
        cents = int(round(float(args.amount) * 100))
        store.set_budget(args.category, cents)
        print(f"Budget set: {args.category} = {plain(cents)}/month")
        return 0
    # show
    now = datetime.now(timezone.utc)
    if args.month:
        y, m = report.parse_month(args.month)
    else:
        y, m = now.year, now.month
    b = report.budget_status(store, year=y, month=m)
    print(f"Budget vs actual — {b['label']}\n")
    if not b["rows"]:
        print("No budgets set. Use: python -m finance budget set <category> <amount>")
    else:
        rows = []
        for r in b["rows"]:
            flag = "OVER" if r["remaining_cents"] < 0 else ""
            rows.append(
                [
                    r["category"],
                    plain(r["actual_cents"]),
                    plain(r["budget_cents"]),
                    dollars(r["remaining_cents"]),
                    f"{round(r['pct']*100)}%",
                    flag,
                ]
            )
        print(
            _table(
                ["Category", "Actual", "Budget", "Remaining", "Used", ""],
                rows,
                aligns=["<", ">", ">", ">", ">", "<"],
            )
        )
        print(
            f"\nTotal: {plain(b['total_actual_cents'])} of "
            f"{plain(b['total_budget_cents'])} budgeted"
        )
    if b["unbudgeted"]:
        print("\nUnbudgeted spending this month:")
        for u in b["unbudgeted"][:8]:
            print(f"  {u['category']:<20} {plain(u['spent_cents'])}")
    return 0


def cmd_categorize(args) -> int:
    store = _store(args)
    categorize.seed_default_rules(store)
    if args.set:
        account_id, txn_id, category = args.set
        store.set_category(account_id, txn_id, category, manual=True)
        print(f"Set {txn_id} → {category} (manual)")
        return 0
    res = categorize.categorize_all(store, rerun=args.rerun)
    print(
        f"Categorized: scanned {res['scanned']}, changed {res['changed']}, "
        f"rule-matched {res['matched']}."
    )
    return 0


def cmd_review(args) -> int:
    store = _store(args)
    start = end = None
    if args.month:
        y, m = report.parse_month(args.month)
        start, end = report.month_bounds(y, m)
    rows = store.transactions(
        start=start,
        end=end,
        uncategorized=args.uncategorized,
        limit=args.limit,
        order="DESC",
    )
    if args.uncategorized:
        rows = [r for r in rows if (r["category"] or "Uncategorized") == "Uncategorized"]
    if not rows:
        print("Nothing to review. 🎉")
        return 0
    cats = store.categories()
    print(f"Reviewing {len(rows)} transaction(s). "
          "Enter a category name, blank to skip, 'q' to quit.")
    if cats:
        print("Known categories: " + ", ".join(cats))
    print()
    non_interactive = not sys.stdin.isatty()
    for r in rows:
        line = (
            f"{report.fmt_date(r['posted'])}  {dollars(r['amount_cents']):>12}  "
            f"{(r['payee'] or r['description'])[:40]:<40}  "
            f"[{r['category'] or 'Uncategorized'}]"
        )
        print(line)
        if non_interactive:
            continue
        try:
            ans = input("  category> ").strip()
        except EOFError:
            break
        if ans.lower() == "q":
            break
        if not ans:
            continue
        store.set_category(r["account_id"], r["txn_id"], ans, manual=True)
        rule = input("  make a rule for this payee? [category or blank]> ").strip()
        if rule:
            pat = (r["payee"] or r["description"]).split("  ")[0][:30]
            store.add_rule(pat, rule, field="both", priority=150)
            print(f"  rule added: '{pat}' → {rule}")
    if non_interactive:
        print("\n(Non-interactive terminal: listing only. Use "
              "`categorize --set <account_id> <txn_id> <category>` to assign.)")
    return 0


def cmd_dashboard(args) -> int:
    store = _store(args)
    out = Path(args.out) if args.out else (store.dir / "dashboard.html")
    dashboard.build(store, out, months=args.months)
    print(f"Wrote dashboard → {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m finance",
        description="SimpleFIN personal finance tracker.",
    )
    p.add_argument("--dir", help="data directory (default: .finance or $FINANCE_DIR)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="store your SimpleFIN token / access URL")
    pi.add_argument("--token", help="SimpleFIN setup token (claimed once)")
    pi.add_argument("--access-url", dest="access_url", help="pre-claimed access URL")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("sync", help="download latest accounts + transactions")
    ps.add_argument("--start", help="only fetch from this date (YYYY-MM-DD)")
    ps.add_argument("--days", type=int, help="only fetch the last N days")
    ps.add_argument("--pending", action="store_true", help="include pending transactions")
    ps.add_argument("--demo", action="store_true", help="use synthetic data (no network)")
    ps.set_defaults(func=cmd_sync)

    pd = sub.add_parser("demo", help="load synthetic data so you can try the tool offline")
    pd.set_defaults(func=cmd_demo)

    sub.add_parser("accounts", help="list accounts and balances").set_defaults(
        func=cmd_accounts
    )

    psp = sub.add_parser("spending", help="spending grouped by category")
    psp.add_argument("--month", help="YYYY-MM (default: current month)")
    psp.add_argument("--from", dest="from_", help="start date YYYY-MM-DD")
    psp.add_argument("--to", help="end date YYYY-MM-DD (exclusive)")
    psp.add_argument("--account", help="restrict to one account id")
    psp.set_defaults(func=cmd_spending)

    pb = sub.add_parser("budget", help="set budgets / show budget vs actual")
    bsub = pb.add_subparsers(dest="budget_cmd")
    bset = bsub.add_parser("set", help="set a monthly budget for a category")
    bset.add_argument("category")
    bset.add_argument("amount", help="dollars per month, e.g. 300")
    pb.add_argument("--month", help="YYYY-MM (default: current month)")
    pb.set_defaults(func=cmd_budget)

    pc = sub.add_parser("categorize", help="apply rules / set a category manually")
    pc.add_argument("--rerun", action="store_true", help="re-evaluate all non-manual rows")
    pc.add_argument(
        "--set",
        nargs=3,
        metavar=("ACCOUNT_ID", "TXN_ID", "CATEGORY"),
        help="manually set one transaction's category",
    )
    pc.set_defaults(func=cmd_categorize)

    pr = sub.add_parser("review", help="walk transactions and categorize them")
    pr.add_argument("--uncategorized", action="store_true", help="only uncategorized")
    pr.add_argument("--month", help="YYYY-MM")
    pr.add_argument("--limit", type=int, default=25, help="max rows (default 25)")
    pr.set_defaults(func=cmd_review)

    pdash = sub.add_parser("dashboard", help="build the HTML dashboard")
    pdash.add_argument("--out", help="output path (default: .finance/dashboard.html)")
    pdash.add_argument("--months", type=int, default=12, help="trend window (default 12)")
    pdash.add_argument("--open", action="store_true", help="open in a browser")
    pdash.set_defaults(func=cmd_dashboard)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

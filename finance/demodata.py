"""Synthetic SimpleFIN-shaped data for offline demos and testing.

``generate()`` returns a dict identical in shape to a real ``/accounts``
response, with dates relative to *today* so the dashboard always has a
populated current month. This lets the whole pipeline (store → categorize →
report → dashboard) be exercised without touching the network.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone


def _ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def generate(months_back: int = 4, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)

    checking, card = [], []
    tid = [0]

    def add(bucket, dt, amount, payee, desc=None):
        tid[0] += 1
        bucket.append(
            {
                "id": f"txn-{tid[0]}",
                "posted": _ts(dt),
                "amount": f"{amount:.2f}",
                "description": desc or payee,
                "payee": payee,
                "memo": "",
                "pending": False,
            }
        )

    # recurring merchants: (payee, category-ish, low, high, per-month count, bucket)
    dining = ["Blue Bottle Coffee", "Chipotle", "Doordash", "Sushi Ran", "Starbucks"]
    groceries = ["Whole Foods Market", "Trader Joe's", "Safeway"]
    shopping = ["Amazon.com", "Target", "Best Buy"]
    gas = ["Shell Oil", "Chevron"]

    for mb in range(months_back, -1, -1):
        # step back mb months from the current month
        y, m = today.year, today.month - mb
        while m <= 0:
            m += 12
            y -= 1
        base = datetime(y, m, 1, 12, tzinfo=timezone.utc)

        def day(d):
            return base.replace(day=min(d, 28))

        # income (twice a month) into checking
        add(checking, day(1), 3200.00, "ACME CORP PAYROLL", "DIRECT DEP ACME CORP")
        add(checking, day(15), 3200.00, "ACME CORP PAYROLL", "DIRECT DEP ACME CORP")
        # rent, utilities from checking
        add(checking, day(3), -2450.00, "Skyline Apartments", "RENT SKYLINE LEASING")
        add(checking, day(8), -142.30, "PG&E", "PGE UTILITY PAYMENT")
        add(checking, day(10), -79.99, "Comcast Xfinity", "XFINITY INTERNET")
        # subscriptions on the card
        add(card, day(5), -15.99, "Netflix", "NETFLIX.COM")
        add(card, day(6), -11.99, "Spotify", "SPOTIFY USA")
        add(card, day(12), -49.99, "Equinox Gym", "EQUINOX FITNESS")
        # variable spend on the card
        for _ in range(rnd.randint(6, 10)):
            p = rnd.choice(dining)
            add(card, day(rnd.randint(2, 27)), -rnd.uniform(6, 48), p)
        for _ in range(rnd.randint(3, 5)):
            p = rnd.choice(groceries)
            add(card, day(rnd.randint(2, 27)), -rnd.uniform(35, 160), p)
        for _ in range(rnd.randint(1, 3)):
            add(card, day(rnd.randint(2, 27)), -rnd.uniform(20, 240), rnd.choice(shopping))
        for _ in range(rnd.randint(1, 3)):
            add(card, day(rnd.randint(2, 27)), -rnd.uniform(28, 62), rnd.choice(gas))
        # monthly credit-card payment: transfer out of checking, into card
        pay = -sum(
            float(t["amount"])
            for t in card
            if _month_of(t) == (y, m) and float(t["amount"]) < 0
        )
        pay = round(pay, 2)
        if pay > 0:
            add(checking, day(20), -pay, "CREDIT CARD PAYMENT", "ONLINE PAYMENT THANK YOU")
            add(card, day(20), pay, "PAYMENT THANK YOU", "AUTOPAY THANK YOU")

    now_ts = _ts(today)
    org = {"name": "Demo Bank", "domain": "demobank.example", "sfin-url": "https://sfin.example"}
    return {
        "errors": [],
        "accounts": [
            {
                "org": org,
                "id": "demo-checking",
                "name": "Everyday Checking",
                "currency": "USD",
                "balance": "8412.55",
                "available-balance": "8412.55",
                "balance-date": now_ts,
                "transactions": sorted(checking, key=lambda t: t["posted"]),
            },
            {
                "org": org,
                "id": "demo-card",
                "name": "Rewards Credit Card",
                "currency": "USD",
                "balance": "-742.18",
                "available-balance": "9257.82",
                "balance-date": now_ts,
                "transactions": sorted(card, key=lambda t: t["posted"]),
            },
        ],
    }


def _month_of(t) -> tuple[int, int]:
    dt = datetime.fromtimestamp(t["posted"], tz=timezone.utc)
    return (dt.year, dt.month)

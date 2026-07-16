# Personal Finance Tracker (SimpleFIN)

A small, self-contained toolkit that pulls your financial data from a
[SimpleFIN Bridge](https://beta-bridge.simplefin.org/) account and helps you
track spending, set budgets, and review/categorize transactions — with a
generated HTML dashboard.

It lives in this repo's `finance/` directory but is completely independent of
the CoStar multifamily dashboard.

## Privacy first

- Your **credentials** (SimpleFIN access URL) and **all financial data** live
  under a git-ignored `.finance/` directory (or in environment variables).
  They are **never committed**.
- SimpleFIN is **read-only** — this tool can see balances and transactions, and
  cannot move money.
- The only network call is the read request to SimpleFIN during `sync`.

## Install

Requires Python 3.9+. The only dependency is `requests`:

```bash
pip install -r finance/requirements.txt
```

Run everything as a module from the repo root: `python -m finance <command>`.

## Try it with no account (offline demo)

```bash
python -m finance demo          # loads synthetic data into .finance/finance.db
python -m finance accounts
python -m finance spending
python -m finance budget set Dining 300
python -m finance budget
python -m finance dashboard --open
```

## Connect your real SimpleFIN account

1. Sign up at **https://beta-bridge.simplefin.org/**, connect your checking and
   credit card, and generate a **Setup Token** (a long base64 string).
2. Claim it once and store the resulting access URL:

   ```bash
   python -m finance init --token <YOUR_SETUP_TOKEN>
   ```

   Already have an access URL? Use `--access-url <URL>` instead. For scheduled /
   cloud use, set `SIMPLEFIN_ACCESS_URL` in the environment instead of `init`.
3. Pull your data:

   ```bash
   python -m finance sync                 # everything the bridge has
   python -m finance sync --days 90       # or just the last 90 days
   python -m finance sync --pending       # include pending transactions
   ```

## Commands

| Command | What it does |
|---|---|
| `init` | Store your SimpleFIN setup token / access URL. |
| `sync` | Download accounts + transactions, upsert, auto-categorize new ones. |
| `demo` | Load synthetic data so you can try everything offline. |
| `accounts` | List accounts and balances. |
| `spending [--month YYYY-MM] [--from --to] [--account]` | Spending grouped by category. |
| `budget set <category> <amount>` / `budget [--month]` | Set budgets; budget vs actual. |
| `review [--uncategorized] [--month] [--limit N]` | Walk transactions and categorize them (interactive). |
| `categorize [--rerun]` / `categorize --set <acct> <txn> <cat>` | Apply rules / set one manually. |
| `dashboard [--out PATH] [--open] [--months N]` | Build the HTML dashboard. |

## How categorization works

- Rules match (case-insensitively) on a transaction's payee/description. The
  highest-`priority` matching rule wins. Defaults ship in
  [`rules.default.json`](rules.default.json) (groceries, dining, gas, rent,
  utilities, subscriptions, income, transfers, …) and are copied into your DB on
  first run.
- Categories you set during `review` are **sticky** — they survive re-running
  `categorize` and future syncs.
- The `Transfer` category (card payments, moving money between your own
  accounts) is **excluded** from spending, income, and budgets so it isn't
  double-counted.

## Running syncs from the cloud environment

Live `sync` needs outbound access to `beta-bridge.simplefin.org`. This repo's
cloud environment currently **blocks** that host at the network policy, so
until an admin allowlists it, run `sync` on your local machine (everything else
works anywhere). Store the access URL as `SIMPLEFIN_ACCESS_URL` for headless /
scheduled runs.

## Data model

SQLite at `.finance/finance.db`: `accounts`, `transactions`
(`(account_id, txn_id)` primary key, upserted on sync), `rules`, `budgets`.
Money is stored as integer cents. Amounts are negative for outflows.

## Tests

```bash
python -m finance.selftest      # offline end-to-end check (no network)
```

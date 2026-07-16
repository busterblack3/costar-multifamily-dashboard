"""SimpleFIN protocol client.

The SimpleFIN flow is deliberately tiny:

1. You get a **setup token** from your SimpleFIN Bridge account. It is a
   base64-encoded *claim URL*.
2. You POST (once) to that claim URL. The response body is an **access URL**
   containing HTTP basic-auth credentials, e.g.
   ``https://USER:PASS@beta-bridge.simplefin.org/simplefin``.
3. You GET ``{access_url}/accounts`` to receive accounts, balances, and
   transactions as JSON.

Amounts come back as decimal *strings* (e.g. ``"-42.19"``); negative means
money left the account. Timestamps are epoch seconds.

This module uses ``requests`` when available (so it transparently honours the
environment's HTTPS proxy and CA bundle) and falls back to the stdlib.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

try:  # pragma: no cover - exercised implicitly
    import requests  # type: ignore

    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False


DEMO_TOKEN = "aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1P"


class SimpleFinError(RuntimeError):
    """Raised when the SimpleFIN bridge returns an error or is unreachable."""


@dataclass
class Organization:
    name: str = ""
    domain: str = ""
    sfin_url: str = ""

    @classmethod
    def from_json(cls, o: Any) -> "Organization":
        if not isinstance(o, dict):
            return cls()
        return cls(
            name=o.get("name") or o.get("domain") or "",
            domain=o.get("domain", ""),
            sfin_url=o.get("sfin-url", ""),
        )


@dataclass
class Transaction:
    id: str
    posted: int
    amount: str
    description: str = ""
    payee: str = ""
    memo: str = ""
    pending: bool = False
    transacted_at: Optional[int] = None

    @classmethod
    def from_json(cls, t: dict) -> "Transaction":
        return cls(
            id=str(t.get("id", "")),
            posted=int(t.get("posted", 0) or 0),
            amount=str(t.get("amount", "0")),
            description=t.get("description", "") or "",
            payee=t.get("payee", "") or "",
            memo=t.get("memo", "") or "",
            pending=bool(t.get("pending", False)),
            transacted_at=(
                int(t["transacted_at"]) if t.get("transacted_at") else None
            ),
        )


@dataclass
class Account:
    id: str
    name: str
    currency: str = "USD"
    balance: str = "0"
    available_balance: Optional[str] = None
    balance_date: int = 0
    org: Organization = field(default_factory=Organization)
    transactions: list[Transaction] = field(default_factory=list)

    @classmethod
    def from_json(cls, a: dict) -> "Account":
        return cls(
            id=str(a.get("id", "")),
            name=a.get("name", "") or "",
            currency=a.get("currency", "USD") or "USD",
            balance=str(a.get("balance", "0")),
            available_balance=(
                str(a["available-balance"])
                if a.get("available-balance") is not None
                else None
            ),
            balance_date=int(a.get("balance-date", 0) or 0),
            org=Organization.from_json(a.get("org")),
            transactions=[
                Transaction.from_json(t) for t in a.get("transactions", []) or []
            ],
        )


@dataclass
class AccountSet:
    accounts: list[Account] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict) -> "AccountSet":
        return cls(
            accounts=[Account.from_json(a) for a in data.get("accounts", []) or []],
            errors=list(data.get("errors", []) or []),
        )


# ---------------------------------------------------------------------------
# Token / access-URL handling
# ---------------------------------------------------------------------------
def decode_setup_token(token: str) -> str:
    """Return the claim URL encoded inside a SimpleFIN setup token."""
    token = token.strip()
    try:
        # SimpleFIN tokens are standard base64; tolerate missing padding.
        padded = token + "=" * (-len(token) % 4)
        url = base64.b64decode(padded).decode("utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        raise SimpleFinError(f"Could not decode setup token: {exc}") from exc
    if not url.lower().startswith("http"):
        raise SimpleFinError("Decoded setup token is not a URL; is it valid?")
    return url


def claim_setup_token(token: str, timeout: int = 30) -> str:
    """Exchange a setup token for a reusable access URL.

    This is a one-time POST to the claim URL. The returned access URL embeds
    basic-auth credentials and should be stored securely.
    """
    claim_url = decode_setup_token(token)
    if _HAVE_REQUESTS:
        try:
            resp = requests.post(claim_url, data=b"", timeout=timeout)
            resp.raise_for_status()
            access_url = resp.text.strip()
        except Exception as exc:  # noqa: BLE001
            raise SimpleFinError(f"Claim request failed: {exc}") from exc
    else:  # pragma: no cover
        req = urllib.request.Request(claim_url, data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                access_url = r.read().decode("utf-8").strip()
        except Exception as exc:  # noqa: BLE001
            raise SimpleFinError(f"Claim request failed: {exc}") from exc
    if not access_url.lower().startswith("http"):
        raise SimpleFinError(f"Unexpected claim response: {access_url[:120]!r}")
    return access_url


def _split_access_url(access_url: str) -> tuple[str, Optional[tuple[str, str]]]:
    """Return (base_url_without_creds, (user, pass) or None)."""
    p = urllib.parse.urlsplit(access_url.strip())
    creds = None
    if p.username is not None:
        creds = (
            urllib.parse.unquote(p.username),
            urllib.parse.unquote(p.password or ""),
        )
    netloc = p.hostname or ""
    if p.port:
        netloc += f":{p.port}"
    base = urllib.parse.urlunsplit((p.scheme, netloc, p.path.rstrip("/"), "", ""))
    return base, creds


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_accounts(
    access_url: str,
    *,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    pending: bool = False,
    account_ids: Optional[list[str]] = None,
    balances_only: bool = False,
    timeout: int = 60,
) -> AccountSet:
    """Fetch accounts + transactions from a SimpleFIN access URL.

    ``start_date`` / ``end_date`` are epoch seconds. ``account_ids`` filters to
    specific accounts.
    """
    base, creds = _split_access_url(access_url)
    params: list[tuple[str, str]] = []
    if start_date is not None:
        params.append(("start-date", str(int(start_date))))
    if end_date is not None:
        params.append(("end-date", str(int(end_date))))
    if pending:
        params.append(("pending", "1"))
    if balances_only:
        params.append(("balances-only", "1"))
    for aid in account_ids or []:
        params.append(("account", aid))

    url = base + "/accounts"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = _get_json(url, creds, timeout)
    return AccountSet.from_json(data)


def _get_json(url: str, creds: Optional[tuple[str, str]], timeout: int) -> dict:
    if _HAVE_REQUESTS:
        try:
            resp = requests.get(url, auth=creds, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise SimpleFinError(f"Request to SimpleFIN failed: {exc}") from exc
        if resp.status_code == 403:
            raise SimpleFinError(
                "403 from SimpleFIN. Either the access URL is invalid, or this "
                "host is blocked by the environment's network policy."
            )
        if resp.status_code >= 400:
            raise SimpleFinError(
                f"SimpleFIN returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise SimpleFinError(f"Invalid JSON from SimpleFIN: {exc}") from exc
    # stdlib fallback  # pragma: no cover
    req = urllib.request.Request(url)
    if creds:
        raw = f"{creds[0]}:{creds[1]}".encode("utf-8")
        req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SimpleFinError(f"Request to SimpleFIN failed: {exc}") from exc

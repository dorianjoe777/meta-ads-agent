#!/usr/bin/env python3
"""Minimal read-only Shopify outcomes connector.

Only aggregate financial outcomes and one-way hashed deduplication keys are
persisted. Customer identity, contact and address fields are never queried.
"""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from local_store import now_iso, read_json, write_json, write_private_json
from product_config import ROOT_DIR


DATA_DIR = ROOT_DIR / "dashboard" / "data"
BUSINESS_OUTCOMES_FILE = DATA_DIR / "business_outcomes.json"
SHOPIFY_SYNC_STATE_FILE = DATA_DIR / "shopify_sync_state.json"
SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
MAX_ORDER_PAGES = 20


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def normalize_shop_domain(value):
    raw = str(value or "").strip().lower()
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Use only the secure *.myshopify.com shop domain.")
        raw = parsed.hostname or ""
    raw = raw.rstrip("/")
    if not SHOP_DOMAIN_RE.fullmatch(raw):
        raise ValueError("Shop domain must end in .myshopify.com and contain no path or credentials.")
    return raw


def money_set(value):
    if not isinstance(value, dict):
        return 0.0, ""
    amount = value.get("shopMoney") or value.get("presentmentMoney") or {}
    return round(number(amount.get("amount")), 2), str(amount.get("currencyCode") or "")


def safe_error(payload, status=0):
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            message = str(errors[0].get("message") if isinstance(errors[0], dict) else errors[0])
        else:
            message = str(payload.get("error") or "Shopify request failed")
    else:
        message = str(payload or "Shopify request failed")
    return {"type": "shopify_api", "status": int(status or 0), "message": message[:300]}


def graphql(shop_domain, token, query, variables=None, api_version="2026-04", timeout=30):
    domain = normalize_shop_domain(shop_domain)
    token = str(token or "").strip()
    if len(token) < 20:
        return {"ok": False, "error": {"type": "configuration", "status": 0, "message": "Missing or invalid Shopify Admin API token."}}
    url = f"https://{domain}/admin/api/{api_version}/graphql.json"
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Shopify-Access-Token": token, "User-Agent": "AdmiraIA/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("errors"):
            return {"ok": False, "error": safe_error(payload)}
        return {"ok": True, "data": payload.get("data") or {}}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": f"Shopify HTTP {exc.code}"}
        return {"ok": False, "error": safe_error(payload, exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": {"type": "network", "status": 0, "message": str(exc)[:300]}}


SHOP_QUERY = """
query AdmiraShopInfo { shop { name currencyCode } }
"""

ORDERS_QUERY = """
query AdmiraOrders($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, sortKey: UPDATED_AT, query: $query) {
    nodes {
      id
      createdAt
      updatedAt
      currencyCode
      cancelledAt
      test
      totalPriceSet { shopMoney { amount currencyCode } }
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      totalRefundedSet { shopMoney { amount currencyCode } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def test_connection(shop_domain, token, api_version="2026-04"):
    result = graphql(shop_domain, token, SHOP_QUERY, api_version=api_version)
    if not result.get("ok"):
        return result
    shop = (result.get("data") or {}).get("shop") or {}
    return {"ok": True, "shop": {"name": str(shop.get("name") or "")[:120], "currency": str(shop.get("currencyCode") or "")}, "scope_required": "read_orders"}


def fetch_orders(shop_domain, token, api_version="2026-04", days=60):
    domain = normalize_shop_domain(shop_domain)
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(60, int(days))))
    query_filter = f"updated_at:>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    rows = []
    cursor = None
    for _ in range(MAX_ORDER_PAGES):
        result = graphql(domain, token, ORDERS_QUERY, {"first": 100, "after": cursor, "query": query_filter}, api_version)
        if not result.get("ok"):
            return {"ok": False, "orders": rows, "error": result.get("error")}
        connection = (result.get("data") or {}).get("orders") or {}
        rows.extend(item for item in connection.get("nodes") or [] if isinstance(item, dict))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return {"ok": True, "orders": rows, "truncated": False}
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return {"ok": True, "orders": rows, "truncated": True}


def hash_order_id(shop_domain, order_id):
    return hashlib.sha256(f"admira-shopify-v1|{shop_domain}|{order_id}".encode("utf-8")).hexdigest()


def aggregate_orders(shop_domain, orders):
    daily = {}
    hashes = []
    for order in orders or []:
        if not isinstance(order, dict) or not order.get("id") or order.get("test"):
            continue
        created = str(order.get("createdAt") or "")
        date_key = created[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_key):
            continue
        gross, currency = money_set(order.get("totalPriceSet"))
        current_total, current_currency = money_set(order.get("currentTotalPriceSet"))
        refunded, refund_currency = money_set(order.get("totalRefundedSet"))
        currency = currency or current_currency or refund_currency
        net = max(0, current_total if current_total or gross == 0 else gross - refunded)
        row = daily.setdefault(date_key, {"date": date_key, "currency": currency, "orders": 0, "cancelled_orders": 0, "gross_sales": 0.0, "refunds": 0.0, "net_sales": 0.0})
        row["orders"] += 1
        row["cancelled_orders"] += 1 if order.get("cancelledAt") else 0
        row["gross_sales"] = round(row["gross_sales"] + gross, 2)
        row["refunds"] = round(row["refunds"] + refunded, 2)
        row["net_sales"] = round(row["net_sales"] + net, 2)
        hashes.append({"hash": hash_order_id(shop_domain, order["id"]), "updated_at": str(order.get("updatedAt") or "")})
    return sorted(daily.values(), key=lambda item: item["date"], reverse=True), hashes


def sync_shopify(shop_domain, token, api_version="2026-04", days=60):
    domain = normalize_shop_domain(shop_domain)
    fetched = fetch_orders(domain, token, api_version, days)
    if not fetched.get("ok"):
        state = read_json(SHOPIFY_SYNC_STATE_FILE, {})
        state.update({"shop_domain": domain, "last_attempt_at": now_iso(), "last_status": "failed", "last_error": fetched.get("error")})
        write_private_json(SHOPIFY_SYNC_STATE_FILE, state, ensure_ascii=False)
        return {"ok": False, "error": fetched.get("error")}
    daily, hashes = aggregate_orders(domain, fetched.get("orders"))
    outcomes = {
        "source": "shopify_admin_api",
        "shop_domain": domain,
        "updated_at": now_iso(),
        "retention_days": 180,
        "privacy": "Daily financial aggregates only; no customer PII or raw order IDs.",
        "days": daily,
    }
    write_json(BUSINESS_OUTCOMES_FILE, outcomes, ensure_ascii=False)
    sync_state = {
        "shop_domain": domain,
        "last_attempt_at": now_iso(),
        "last_success_at": now_iso(),
        "last_status": "complete",
        "api_version": api_version,
        "orders_seen": len(hashes),
        "truncated": bool(fetched.get("truncated")),
        "dedup_keys": hashes,
    }
    write_private_json(SHOPIFY_SYNC_STATE_FILE, sync_state, ensure_ascii=False)
    return {"ok": True, "shop_domain": domain, "days": len(daily), "orders_seen": len(hashes), "truncated": bool(fetched.get("truncated")), "outcomes": outcomes}


def shopify_status(config):
    state = read_json(SHOPIFY_SYNC_STATE_FILE, {})
    outcomes = read_json(BUSINESS_OUTCOMES_FILE, {})
    domain = str(getattr(config, "shopify_shop_domain", "") or "")
    return {
        "configured": bool(domain and getattr(config, "shopify_admin_token", "")),
        "shop_domain": domain,
        "token_set": bool(getattr(config, "shopify_admin_token", "")),
        "api_version": getattr(config, "shopify_api_version", "2026-04"),
        "last_success_at": state.get("last_success_at", ""),
        "last_status": state.get("last_status", "never"),
        "orders_seen": int(number(state.get("orders_seen"))),
        "aggregate_days": len(outcomes.get("days") or []),
        "privacy": "Aggregates only; no customer PII.",
    }

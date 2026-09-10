"""Tenant-local annual evidence cache; never replaces the live 30-day snapshot."""
import fcntl
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from local_store import read_json, atomic_write_json as write_json

TTL_SECONDS = 6 * 3600
RETRY_SECONDS = 300


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def cache_path(root, account_id, page_id):
    key = hashlib.sha256(f"{page_id}:{account_id}".encode()).hexdigest()[:24]
    return Path(root) / "meta_history" / (key + ".json")


def digest(metrics):
    rows = [row for row in metrics.get("campaigns", []) if isinstance(row, dict)]
    totals = {}
    for key in ("spend", "impressions", "clicks", "conversions", "revenue"):
        values = [_number(row.get(key)) for row in rows]
        totals[key] = round(sum(value for value in values if value is not None), 2) if any(value is not None for value in values) else None
    for label, numerator, denominator, multiplier in (
        ("ctr", "clicks", "impressions", 100), ("cpc", "spend", "clicks", 1),
        ("cpa", "spend", "conversions", 1), ("roas", "revenue", "spend", 1),
    ):
        totals[label] = round(totals[numerator] / totals[denominator] * multiplier, 4) if totals.get(denominator) and totals.get(numerator) is not None else None
    for key in ("leads", "purchases"):
        values = [_number((row.get("funnel") or {}).get("purchase" if key == "purchases" else "lead")) for row in rows]
        totals[key] = round(sum(value for value in values if value is not None), 2) if any(value is not None for value in values) else None
    totals["cpl"] = round(totals["spend"] / totals["leads"], 2) if totals.get("leads") and totals.get("spend") is not None else None
    # Reach is not additive across campaigns; never fabricate account unique reach.
    totals["reach"] = (metrics.get("summary") or {}).get("reach")
    keys = ("id", "name", "status", "objective", "spend", "impressions", "clicks", "conversions", "revenue", "funnel")
    ranked = sorted(rows, key=lambda row: _number(row.get("spend")) or 0, reverse=True)
    return {"kpis": totals, "campaign_count": len(rows),
            "top_campaigns": [{key: str(row[key])[:100] if key == "name" else row[key] for key in keys if key in row} for row in ranked[:8]],
            "interpretation": "Historical evidence only. Conversions aggregate heterogeneous objectives; use campaign-specific funnel KPIs for decisions. Live 30d wins on current state."}


def history_context(root, account_id, page_id, *, refresh=False, fetch=None, launch=None, now=None, campaign_id="", offset=0, limit=25, account_timezone="UTC", reserved=False):
    now = now or datetime.now(timezone.utc)
    if not account_id or not page_id:
        return {"status": "unavailable", "reason": "workspace_not_selected"}
    path = cache_path(root, account_id, page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_json(path, {})
    fetched_epoch = float(state.get("fetched_epoch") or 0)
    stale = now.timestamp() - fetched_epoch >= TTL_SECONDS
    last_attempt = float(state.get("attempt_epoch") or 0)
    due = stale and (reserved or now.timestamp() - last_attempt >= RETRY_SECONDS)
    if due and (refresh or launch):
        with path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                due = False
            else:
                latest = read_json(path, {})
                latest_stale = now.timestamp() - float(latest.get("fetched_epoch") or 0) >= TTL_SECONDS
                if latest_stale and (reserved or now.timestamp() - float(latest.get("attempt_epoch") or 0) >= RETRY_SECONDS):
                    state = {**latest, "attempt_epoch": now.timestamp()}
                    write_json(path, state)
                    if refresh and fetch:
                        try:
                            # Full closed days; exact 365-day range in the account's selected timezone.
                            try:
                                local_date = now.astimezone(ZoneInfo(account_timezone)).date()
                            except ZoneInfoNotFoundError:
                                local_date = now.date()
                            until = (local_date - timedelta(days=1)).isoformat()
                            since = (local_date - timedelta(days=365)).isoformat()
                            result = fetch(account_id, since=since, until=until)
                            metrics = result.get("metrics") or {}
                            returned_account = str(metrics.get("account_id") or result.get("account_id") or "")
                            if result.get("ok") and not result.get("partial") and returned_account.removeprefix("act_") == str(account_id).removeprefix("act_"):
                                state.update(metrics=metrics, digest=digest(metrics), as_of=now.isoformat(),
                                             fetched_epoch=now.timestamp(), since=since, until=until, error="")
                            else:
                                state["error"] = "partial_or_failed_annual_read"
                        except Exception as exc:
                            state["error"] = type(exc).__name__
                        write_json(path, state)
                    elif launch:
                        try:
                            launch(account_id, page_id)
                        except OSError as exc:
                            state["error"] = type(exc).__name__
                            write_json(path, state)
    state = read_json(path, state)
    age = now.timestamp() - float(state.get("fetched_epoch") or 0)
    output = {"status": "fresh" if state.get("digest") and age < TTL_SECONDS else "stale" if state.get("digest") else "pending",
              "account_id": account_id, "page_id": page_id, "window": "last_365d",
              "as_of": state.get("as_of", ""), "since": state.get("since", ""), "until": state.get("until", ""),
              "refresh_error": state.get("error", ""), "digest": state.get("digest") or {},
              "detail_tool": "mcp_admira_get_meta_history_context"}
    if refresh or campaign_id:
        rows = (state.get("metrics") or {}).get("campaigns") or []
        if campaign_id:
            rows = [row for row in rows if str(row.get("id") or row.get("campaign_id")) == campaign_id]
        output.update(campaigns=rows[offset:offset + limit], total=len(rows), next_offset=offset + limit if len(rows) > offset + limit else None)
    return output


def launch_refresh(product_root, account_id, page_id):
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(product_root), account_id, page_id],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=True)


if __name__ == "__main__":
    import importlib.util
    root, account, page = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location("annual_history_dashboard", Path(root) / "dashboard/monitoring-dashboard.py")
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    if dashboard.active_meta_page_id() == page and str(dashboard.current_configured_ad_account_id()).removeprefix("act_") == account.removeprefix("act_"):
        # Honor the parent's reservation without clearing the cooldown and
        # opening a race for another foreground turn to launch a second worker.
        dashboard.get_meta_history_context(reserved=True)

"""Upcoming events: central-bank meetings and your own entries (data/events.json),
key US data releases (FRED, free key), and earnings dates (yfinance)."""
import os
from datetime import date, timedelta

import requests

FRED_URL = "https://api.stlouisfed.org/fred/releases/dates"
KEY_RELEASES = {
    "Consumer Price Index": "US CPI (inflation)",
    "Employment Situation": "US jobs report",
    "Gross Domestic Product": "US GDP",
    "Personal Income and Outlays": "US PCE inflation",
    "Producer Price Index": "US PPI",
    "Job Openings and Labor Turnover Survey": "US job openings (JOLTS)",
    "Advance Monthly Sales for Retail and Food Services": "US retail sales",
}


def fred_releases(start, end):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(FRED_URL, timeout=30, params={
            "api_key": key, "file_type": "json", "realtime_start": start, "realtime_end": end,
            "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 1000})
        r.raise_for_status()
        out = []
        for d in r.json().get("release_dates", []):
            name = d.get("release_name", "")
            for k, label in KEY_RELEASES.items():
                if name.startswith(k):
                    out.append({"date": d["date"], "title": label, "kind": "Data release",
                                "detail": name, "source": "https://fred.stlouisfed.org/releases/calendar"})
        return out
    except (requests.RequestException, ValueError) as e:
        print("  FRED failed:", e)
        return []


def build(custom_events, fred, earnings, companies, today, days):
    """earnings: {ticker: [iso dates]}. Returns sorted list within the window, de-duplicated."""
    start = date.fromisoformat(today)
    end = start + timedelta(days=days)
    by_ticker = {c.get("ticker"): c for c in companies if c.get("ticker")}
    rows = []
    for e in custom_events:
        rows.append(dict(e, kind=e.get("kind", "Event")))
    rows.extend(fred)
    for tkr, dates in earnings.items():
        c = by_ticker.get(tkr, {})
        for d in dates:
            rows.append({"date": d, "title": f"{c.get('name', tkr)} earnings", "kind": "Earnings",
                         "detail": tkr, "company": c.get("name", "")})
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: (x["date"], x["title"])):
        try:
            d = date.fromisoformat(r["date"][:10])
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        k = (r["date"], r["title"])
        if k in seen:
            continue
        seen.add(k)
        r = dict(r)
        r["days_away"] = (d - start).days
        r["weekday"] = d.strftime("%a")
        r["day"] = d.strftime("%d %b")
        out.append(r)
    return out

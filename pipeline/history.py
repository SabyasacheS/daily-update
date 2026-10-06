"""Memory between runs: which headlines were already shown, and daily snapshots for 'What changed'."""
import glob
import os
from datetime import date, timedelta

from .config import HISTORY_DIR, SEEN, load_json, save_json


def mark_new(all_items, today, keep_days=21):
    """Sets item['is_new'] = first seen today. Updates and prunes data/seen.json."""
    seen = load_json(SEEN, {})
    for it in all_items:
        first = seen.get(it["id"])
        if not first:
            seen[it["id"]] = today
            first = today
        it["is_new"] = first == today
    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    save_json(SEEN, seen)


def previous_snapshot(today):
    files = sorted(f for f in glob.glob(os.path.join(HISTORY_DIR, "*.json"))
                   if os.path.basename(f)[:10] < today)
    return load_json(files[-1], None) if files else None


def save_snapshot(today, report):
    snap = {
        "date": today,
        "quotes": {h["name"]: {"price": h["q"]["price"], "change_pct": h["q"]["change_pct"]}
                   for h in report["holdings"] if h.get("q")},
        "valuations": {n: c["view"].get("valuation", {}).get("text") for n, c in report["companies"].items()
                       if c["view"].get("valuation")},
        "items": {n: [i["id"] for i in c["items"]] for n, c in report["companies"].items()},
    }
    save_json(os.path.join(HISTORY_DIR, f"{today}.json"), snap)


def diff(report, prev, val_changes, signals, filtered):
    companies = report["companies"]
    new_pr, new_news = [], []
    for name, c in companies.items():
        for it in c["items"]:
            if it.get("is_new"):
                (new_pr if it["kind"] == "pr" else new_news).append(dict(it, company=name))
    key = lambda x: x.get("ts", "")
    quiet = sorted(n for n, c in companies.items() if not any(i.get("is_new") for i in c["items"]))
    soon = [e for e in report["calendar"] if e["days_away"] <= 2]
    return {
        "since": prev["date"] if prev else None,
        "moves": [h for h in report["holdings"] if h.get("q") and h["q"]["flags"]],
        "valuations": val_changes,
        "signals": signals,
        "new_pr": sorted(new_pr, key=key, reverse=True),
        "new_news": sorted(new_news, key=key, reverse=True),
        "calendar_soon": soon,
        "quiet": quiet,
        "filtered": filtered[:12],
        "filtered_count": len(filtered),
    }

"""Paths, settings loading and the house formatting rules.

Formatting rules (agreed with the reader):
  * currency codes, never symbols  -> "USD 190bn", "EUR 12.15"
  * units bn / m / tn              -> "USD 100m", "132.7m"
  * approximations use "c."        -> "c. USD 852bn"
  * negatives use a minus sign     -> "−4.30%", never "(4.30)"
"""
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(ROOT, "watchlist.json")
EVENTS = os.path.join(ROOT, "data", "events.json")
VALUATIONS = os.path.join(ROOT, "data", "valuations.json")
STATE = os.path.join(ROOT, "data", "state.json")
SEEN = os.path.join(ROOT, "data", "seen.json")
HISTORY_DIR = os.path.join(ROOT, "data", "history")
DOCS = os.path.join(ROOT, "docs")
TEMPLATES = os.path.join(ROOT, "templates")

MINUS = "\u2212"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_watchlist():
    wl = load_json(WATCHLIST, {})
    wl.setdefault("settings", {})
    wl.setdefault("companies", [])
    wl.setdefault("sections", [])
    wl.setdefault("industry", [])
    wl.setdefault("macro", [])
    wl.setdefault("busy_focus", [])
    for c in wl["companies"]:
        c.setdefault("sections", [])
        c.setdefault("aliases", [c["name"]])
        if not c["aliases"]:
            c["aliases"] = [c["name"]]
        c.setdefault("must", [])
        c.setdefault("domain", "")
        c.setdefault("ticker", "")
    return wl


def now_utc():
    return datetime.now(timezone.utc)


def local_now(settings):
    return now_utc().astimezone(ZoneInfo(settings.get("timezone", "Asia/Qatar")))


# ---------- formatting ----------

def _trim(x, digits):
    s = f"{x:,.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_big(amount, currency="USD", approx=False):
    """190e9 -> 'USD 190bn'; 1.2e12 -> 'USD 1.2tn'; 1e8 -> 'USD 100m'."""
    if amount is None:
        return ""
    a = float(amount)
    if abs(a) >= 1e12:
        body = _trim(a / 1e12, 2) + "tn"
    elif abs(a) >= 1e9:
        body = _trim(a / 1e9, 2) + "bn"
    elif abs(a) >= 1e6:
        body = _trim(a / 1e6, 1) + "m"
    else:
        body = _trim(a, 0)
    out = f"{currency} {body}".strip()
    return ("c. " + out) if approx else out


def fmt_price(x, digits=2):
    if x is None:
        return "n/a"
    return f"{x:,.{digits}f}"


def fmt_pct(x, digits=2):
    if x is None:
        return "n/a"
    sign = "+" if x > 0 else (MINUS if x < 0 else "")
    return f"{sign}{abs(x):.{digits}f}%"


def fmt_signed(x, digits=2):
    if x is None:
        return "n/a"
    sign = "+" if x > 0 else (MINUS if x < 0 else "")
    return f"{sign}{abs(x):,.{digits}f}"


def fmt_vol_m(shares):
    """Shares -> millions with 'm' handled by the template header. Returns '132.73'."""
    if shares is None:
        return "n/a"
    return f"{shares / 1e6:,.2f}"


def fmt_ratio(x):
    if x is None:
        return "n/a"
    return f"{x:.1f}\u00d7"


def fmt_date_short(iso):
    """'2026-10-05' -> '05 Oct'."""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d %b")
    except (ValueError, TypeError):
        return iso or ""


def house_style(text):
    """Rewrite '$190B', '~$5 billion', '132.7M' etc. into the house style.
    Applied to AI output and headlines we display in our own words."""
    if not text:
        return text
    t = text
    t = re.sub(r"~\s*(?=[$\d])", "c. ", t)
    unit_map = {"trillion": "tn", "tn": "tn", "t": "tn", "billion": "bn", "bn": "bn", "b": "bn",
                "million": "m", "mn": "m", "m": "m"}

    def money(m):
        num, unit = m.group(1), (m.group(2) or "").lower()
        return f"USD {num}{unit_map.get(unit, '')}" if unit else f"USD {num}"

    t = re.sub(r"(?:US)?\$\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|billion|million|tn|bn|mn|[TtBbMm])?\b", money, t)
    t = re.sub(r"€\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|billion|million|tn|bn|mn|[TtBbMm])?\b",
               lambda m: f"EUR {m.group(1)}{unit_map.get((m.group(2) or '').lower(), '')}", t)
    t = re.sub(r"£\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|billion|million|tn|bn|mn|[TtBbMm])?\b",
               lambda m: f"GBP {m.group(1)}{unit_map.get((m.group(2) or '').lower(), '')}", t)
    return t

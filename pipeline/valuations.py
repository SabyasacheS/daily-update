"""Keeps private-company valuations current.

Each run, funding-related headlines are turned into candidates (by the AI when a key is set,
otherwise by regex). A candidate is only accepted if its number literally appears in the source
text, which stops invented figures. "Closed" rounds replace the valuation on file; "reported"
ones (in talks, seeking...) are shown beside it until confirmed. Pinned values never change.
"""
import json
import re

from .config import fmt_big

AMOUNT = (r"(?:(?:US)?\$|USD\s?|\u20ac|EUR\s?|\u00a3|GBP\s?)\s?(\d+(?:[.,]\d+)?)\s?"
          r"(trillion|billion|million|tn|bn|mn|[tbm])\b")
AMOUNT_RE = re.compile(AMOUNT, re.I)
MULT = {"trillion": 1e12, "tn": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
        "million": 1e6, "mn": 1e6, "m": 1e6}
FUNDING_RE = re.compile(
    r"\b(valuation|valued|valuing|raises?|raised|raising|funding|financing|round|series [a-h]|investment|"
    r"invests?|stake|ipo|s-1|lines up|credit facility|tender offer|secondary sale)\b", re.I)
REPORTED_RE = re.compile(
    r"\b(talks?|seeks?|seeking|plans?|planning|consider(s|ing)?|could|eyes|eyeing|reportedly|targets?|targeting|"
    r"aims?|weighs?|exploring|said to|sources|lines up|lining up|discussions?|nears?|in line for|would)\b", re.I)
CLOSED_RE = re.compile(r"\b(closes?|closed|raised|raises|completes?|completed|secures?|secured|announces?|"
                       r"announced|lands|bags|final close)\b", re.I)
VALUATION_RE = re.compile(r"(valuation|valued|valuing|value[sd]? at)", re.I)


def currency_of(raw):
    r = raw.upper()
    if "\u20ac" in raw or "EUR" in r:
        return "EUR"
    if "\u00a3" in raw or "GBP" in r:
        return "GBP"
    return "USD"


def parse_amounts(text):
    out = []
    for m in AMOUNT_RE.finditer(text or ""):
        num = float(m.group(1).replace(",", "."))
        out.append({"value": num * MULT[m.group(2).lower()], "currency": currency_of(m.group(0)),
                    "start": m.start(), "end": m.end()})
    return out


def number_in_text(value, text):
    return any(abs(a["value"] - value) <= 0.011 * value for a in parse_amounts(text)) if value else False


def classify_status(text):
    if REPORTED_RE.search(text):
        return "reported"
    if CLOSED_RE.search(text):
        return "closed"
    return "reported"


def regex_extract(text):
    """Best-effort extraction without AI. Returns dict or None."""
    amts = parse_amounts(text)
    if not amts:
        return None
    val = None
    for a in amts:
        before = text[max(0, a["start"] - 45):a["start"]]
        after = text[a["end"]:a["end"] + 14]
        if VALUATION_RE.search(before) or re.match(r"\s*(post-money\s+|pre-money\s+)?valuation", after, re.I):
            val = a
            break
    rest = [a for a in amts if a is not val]
    raise_amt = None
    for a in rest:
        before = text[max(0, a["start"] - 28):a["start"]]
        after = text[a["end"]:a["end"] + 22]
        if re.match(r"\s*(in\s+)?(new\s+)?(funding\s+|equity\s+|series [a-h]\s+)?(round|raise|funding|financing|investment)", after, re.I) \
                or re.search(r"(raises?|raising|raised|lines? up|lining up|secures?|closes?|closed|seeks?|seeking)\s+(about |nearly |up to )?$", before, re.I):
            raise_amt = a
            break
    if raise_amt is None and rest:
        raise_amt = rest[-1]
    if not val and not raise_amt:
        return None
    return {"valuation": val["value"] if val else None, "currency": (val or raise_amt)["currency"],
            "raise_amount": raise_amt["value"] if raise_amt else None, "status": classify_status(text)}


def candidates(items):
    return [it for it in items if FUNDING_RE.search(it["title"] + " " + it.get("snippet", ""))]


def validate(extraction, text):
    """Drop numbers that do not appear in the source text."""
    if not extraction:
        return None
    e = dict(extraction)
    if e.get("valuation") and not number_in_text(e["valuation"], text):
        e["valuation"] = None
    if e.get("raise_amount") and not number_in_text(e["raise_amount"], text):
        e["raise_amount"] = None
    if not e.get("valuation") and not e.get("raise_amount"):
        return None
    if e.get("status") not in ("closed", "reported"):
        e["status"] = classify_status(text)
    return e


SCHEMA = 2


SUBJECT_VERBS = (r"(raises?|raised|raising|valued|valuation|closes?|closed|secures?|secured|seeks?|seeking|lands|"
                 r"lines up|lining up|in talks|hits|reaches|nears|eyes|targets|files|bags|gets|wins)")


def is_subject(title, aliases):
    """True if the headline is about the company's own funding: it starts with the company name, or the name is
    followed within a few words by a funding verb. Stops 'The TikTok Live Playbook: How Skimpies Scaled to a
    USD 10m Valuation' being read as TikTok's valuation."""
    t = re.sub(r"^\s*(exclusive|breaking|report|update|scoop|sources?)\s*[:\-\u2013\u2014|]\s*", "", title, flags=re.I)
    for a in aliases:
        if not a:
            continue
        if re.match(re.escape(a) + r"(?![A-Za-z0-9])", t, re.I):
            return True
        m = re.search(r"(\w+)?\W*" + re.escape(a) + r"(?:'s)?\W+(?:\w+\W+){0,3}?" + SUBJECT_VERBS + r"\b", t, re.I)
        if m and (m.group(1) or "").lower() not in ("on", "with", "using", "via", "for", "to", "from", "of", "by",
                                                    "about", "and", "like", "rival", "rivals", "than", "vs", "at", "in"):
            return True
    return False


def seed_all(state, companies, verified):
    """Start from verified, sourced valuations (data/valuations.json) or a value pinned on the Watchlist page.
    Unsourced 'manual' figures are no longer used: without a source the card shows NA."""
    if state.get("schema", 1) < SCHEMA:
        for k in ("valuations", "reported", "last_round", "seeds", "val_checked"):
            state.pop(k, None)
        state["schema"] = SCHEMA
    vals = state.setdefault("valuations", {})
    reported = state.setdefault("reported", {})
    seeds = state.setdefault("seeds", {})
    for c in companies:
        name = c["name"]
        pin = c.get("valuation") if (c.get("valuation") or {}).get("pinned") else None
        src = pin or verified.get(name)
        if not src:
            if vals.get(name, {}).get("status") == "pinned":
                vals.pop(name)  # pin was removed on the Watchlist page
            continue
        key = json.dumps(src, sort_keys=True)
        if seeds.get(name) == key:
            continue
        seeds[name] = key
        cur = vals.get(name)
        if not pin and cur and cur.get("status") in ("closed", "implied") and cur.get("date", "") > src.get("date", ""):
            continue  # the daily run already found something newer than the register
        vals[name] = {
            "amount": src.get("amount"), "currency": src.get("currency", "USD"),
            "text": src.get("text") or fmt_big(src.get("amount"), src.get("currency", "USD"), src.get("approx")),
            "status": "pinned" if pin else src.get("status", "closed"), "date": src.get("date", ""),
            "approx": bool(src.get("approx")), "note": src.get("note", ""),
            "source_title": src.get("source_title", ""), "source_url": src.get("source_url", ""),
        }
        if src.get("reported") and not pin:
            r = src["reported"]
            reported[name] = {"amount": r.get("amount"), "currency": r.get("currency", "USD"), "text": r["text"],
                              "date": r.get("date", ""), "source_title": r.get("source_title", ""),
                              "source_url": r.get("source_url", ""), "status": "reported"}


def apply(state, name, ext, item, today):
    """Apply one validated extraction. Returns a change record or None."""
    vals = state.setdefault("valuations", {})
    reported = state.setdefault("reported", {})
    rounds = state.setdefault("last_round", {})
    cur = vals.get(name)
    date = item.get("date") or today
    src = {"source_title": item["title"], "source_url": item["url"], "date": date, "source": item.get("source", "")}
    change = None

    if ext.get("raise_amount"):
        prev_round = rounds.get(name)
        if not prev_round or date >= prev_round.get("date", ""):
            rounds[name] = dict(src, text=fmt_big(ext["raise_amount"], ext["currency"]), status=ext["status"])

    v = ext.get("valuation")
    if not v:
        return {"type": "signal", "company": name, "status": ext["status"],
                "raise_text": fmt_big(ext["raise_amount"], ext["currency"]) if ext.get("raise_amount") else "",
                **src}
    text = fmt_big(v, ext["currency"])
    if cur and cur.get("status") == "pinned":
        return None
    if ext["status"] == "closed":
        same = cur and cur.get("amount") and abs(cur["amount"] - v) <= 0.011 * v
        newer = not cur or not cur.get("date") or date >= cur.get("date", "")
        if same:
            reported.pop(name, None)
        elif newer:
            vals[name] = dict(src, amount=v, currency=ext["currency"], text=text, status="closed",
                              approx=False, updated_on=today,
                              previous={k: cur.get(k) for k in ("text", "amount", "date", "status")} if cur else None)
            reported.pop(name, None)
            change = {"type": "valuation", "company": name, "from": cur.get("text") if cur else "",
                      "to": text, **src}
    else:
        old = reported.get(name)
        if not old or old.get("amount") != v or date > old.get("date", ""):
            reported[name] = dict(src, amount=v, currency=ext["currency"], text=text, status="reported")
            change = {"type": "reported", "company": name, "to": text, **src}
    return change


def _long(iso):
    try:
        from datetime import date as _d
        return _d.fromisoformat(iso[:10]).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return iso or ""


def card_view(state, name, today=""):
    """What a company card shows. The old value is shown for 14 days after an update."""
    from datetime import date as _d, timedelta as _td
    v = state.get("valuations", {}).get(name)
    r = state.get("reported", {}).get(name)
    rd = state.get("last_round", {}).get(name)
    view = {}
    labels = {"closed": "round closed", "implied": "implied by deal", "reported": "reported, not confirmed",
              "pinned": "entered by you"}
    if v and v.get("text"):
        when = _long(v.get("date", ""))
        view["valuation"] = {"text": v["text"], "url": v.get("source_url", ""), "note": v.get("note", ""),
                             "provenance": labels.get(v.get("status"), v.get("status", "")) + (f" \u00b7 {when}" if when else ""),
                             "previous": (v.get("previous") or {}).get("text") if v.get("updated_on") and today and
                             v["updated_on"] >= (_d.fromisoformat(today) - _td(days=14)).isoformat() else None}
    else:
        view["valuation"] = {"text": "NA", "provenance": "no public valuation found", "url": "", "note": "",
                             "previous": None, "na": True}
    if r:
        view["reported"] = {"text": r["text"], "date": r["date"], "url": r["source_url"]}
    if rd:
        view["last_round"] = {"text": rd["text"], "status": rd["status"], "date": rd["date"], "url": rd["source_url"]}
    return view

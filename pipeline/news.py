"""Google News RSS: fetch, filter noise, tag press releases, cluster duplicates.

Free, no API key. Every item keeps a link to its original source.
"""
import hashlib
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; DailyUpdate/2.0)"}
RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

JUNK_TITLE = re.compile(
    r"\b(careers?|job openings?|jobs at|cookie|privacy policy|terms of (use|service)|sign ?in|log ?in|"
    r"api|documentation|docs|download|installation|licensing|word of the day|quiz|price prediction|"
    r"presale|giveaway|airdrop|stock price today|stock quote|share price chart|wallpaper|lyrics|"
    r"horoscope|coupon|promo code)\b",
    re.I,
)
JUNK_SOURCES = {"britannica", "wikipedia", "linkedin.com", "youtube", "facebook", "instagram", "x.com", "reddit"}
STOP = set("a an the and or of to in on for at by with from as is are be its it this that new after over into amid "
           "says said will could may vs than up down".split())


def _get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.status_code in (429, 503):
                time.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            if i == tries - 1:
                print("  news fetch failed:", e)
            time.sleep(2 * (i + 1))
    return ""


def fetch_rss(query):
    time.sleep(0.6)  # be polite to Google News
    return _get(RSS.format(q=urllib.parse.quote(query)))


def clean_title(t):
    t = html.unescape(t or "").strip()
    for sep in (" - ", " | ", " \u2014 ", " \u2013 "):
        if sep in t:
            head, tail = t.rsplit(sep, 1)
            if 0 < len(tail) <= 60 and len(head) > 15:
                t = head
    return re.sub(r"\s+", " ", t).strip()


def parse_rss(xml_text):
    items = []
    if not xml_text:
        return items
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = clean_title(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        source_url = (src_el.get("url") or "") if src_el is not None else ""
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "")
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pub = None
        snippet = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if title and link:
            items.append({"title": title, "url": link, "source": source or "Google News",
                          "source_url": source_url, "pub": pub, "snippet": snippet})
    return items


def item_id(title):
    norm = re.sub(r"[^a-z0-9 ]", "", title.lower())
    return hashlib.sha1(norm[:90].encode()).hexdigest()[:12]


def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2 and w not in STOP}


def _mentions(text, phrases):
    for p in phrases:
        if not p:
            continue
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(p) + r"(?![A-Za-z0-9])", text, re.I):
            return True
    return False


def junk_reason(raw):
    title = raw["title"]
    if JUNK_TITLE.search(title):
        return "not a news item"
    src = (raw.get("source") or "").lower()
    if any(j in src for j in JUNK_SOURCES):
        return "reference or social page"
    if len(title.split()) < 3:
        return "title too short to be news"
    return None


def finalize(raw, kind):
    pub = raw["pub"]
    return {
        "id": item_id(raw["title"]),
        "title": raw["title"],
        "url": raw["url"],
        "source": raw["source"],
        "date": pub.strftime("%Y-%m-%d") if pub else "",
        "ts": pub.isoformat() if pub else "",
        "kind": kind,
        "sources": [raw["source"]],
    }


def cluster(items, limit=None):
    """Merge near-duplicate headlines about the same story; keep the press release if there is one."""
    out = []
    for it in sorted(items, key=lambda x: (x["kind"] != "pr", x["ts"] or "")):
        toks = _tokens(it["title"])
        match = None
        for o in out:
            ot = o["_tok"]
            if toks and ot and len(toks & ot) / len(toks | ot) >= 0.5:
                match = o
                break
        if match:
            if it["source"] not in match["sources"]:
                match["sources"].append(it["source"])
            if it["ts"] > match["ts"] and match["kind"] != "pr":
                match["ts"], match["date"] = it["ts"], it["date"]
        else:
            it = dict(it)
            it["_tok"] = toks
            out.append(it)
    for o in out:
        o.pop("_tok", None)
    out.sort(key=lambda x: x["ts"] or "", reverse=True)
    return out[:limit] if limit else out


def _window_ok(raw, cutoff):
    return raw["pub"] is not None and raw["pub"] >= cutoff


def company_news(company, window_hours, busy_focus, fetch=fetch_rss, limit=6):
    """Returns (items, filtered). filtered = [{'company','title','reason'}]."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    days = max(1, round(window_hours / 24))
    aliases = company["aliases"]
    domain = (company.get("domain") or "").lower()
    found, filtered = [], []

    q = " OR ".join(f'"{a}"' for a in aliases) + f" when:{days}d"
    for raw in parse_rss(fetch(q)):
        if not _window_ok(raw, cutoff):
            continue
        is_pr = bool(domain) and domain.split("/")[0] in (raw.get("source_url") or "").lower()
        if not _mentions(raw["title"], aliases):
            continue  # story is not about this company (or only mentions it in passing)
        reason = junk_reason(raw)
        if not reason and company.get("must") and not is_pr and not _mentions(raw["title"], company["must"]):
            reason = "name match without context words"
        if not reason and company.get("busy") and not is_pr and not _mentions(raw["title"], busy_focus):
            reason = "routine coverage of a large firm"
        if reason:
            filtered.append({"company": company["name"], "title": raw["title"], "reason": reason})
            continue
        found.append(finalize(raw, "pr" if is_pr else "news"))

    if domain:
        for raw in parse_rss(fetch(f"site:{domain} when:7d")):
            if not _window_ok(raw, cutoff):
                continue
            reason = junk_reason(raw)
            if reason:
                filtered.append({"company": company["name"], "title": raw["title"], "reason": reason})
                continue
            found.append(finalize(raw, "pr"))

    return cluster(found, limit), filtered


def topic_news(query, window_hours, fetch=fetch_rss, limit=3):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    days = max(1, round(window_hours / 24))
    out = []
    for raw in parse_rss(fetch(f"{query} when:{days}d")):
        if _window_ok(raw, cutoff) and not junk_reason(raw):
            out.append(finalize(raw, "news"))
    return cluster(out, limit)


def valuation_search(company, fetch=fetch_rss, days=180, limit=10):
    """Longer look-back used to backfill a missing or stale valuation."""
    names = " OR ".join(f'"{a}"' for a in company["aliases"][:2])
    q = f"({names}) (valuation OR valued OR raises OR funding) when:{days}d"
    out = []
    for raw in parse_rss(fetch(q)):
        if raw["pub"] and _mentions(raw["title"], company["aliases"]) and not junk_reason(raw):
            it = finalize(raw, "news")
            it["snippet"] = raw.get("snippet", "")
            out.append(it)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit]

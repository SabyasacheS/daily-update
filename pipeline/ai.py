"""Gemini (free tier) for two jobs: reading funding headlines, and writing the briefing.

Everything here is optional. With no GEMINI_API_KEY, or if a call fails, the pipeline
falls back to rule-based output, so the report always ships.
"""
import json
import os
import re
import time

import requests

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


_QUOTA_GONE = False


def available():
    return bool(os.environ.get("GEMINI_API_KEY")) and not _QUOTA_GONE


def _call(prompt, model, tries=3, timeout=240):
    global _QUOTA_GONE
    key = os.environ.get("GEMINI_API_KEY")
    if not key or _QUOTA_GONE:
        return None
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    for i in range(tries):
        try:
            r = requests.post(URL.format(model=model), json=body, timeout=timeout,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            if r.status_code == 429 and "quota" in r.text.lower():
                _QUOTA_GONE = True
                print("  AI daily quota used up; continuing without AI for this run")
                return None
            if r.status_code in (429, 500, 503):
                print(f"  AI busy or rate-limited ({r.status_code}): {r.text[:160]}")
                time.sleep(30 * (i + 1))
                continue
            if r.status_code >= 400:
                print("  AI error", r.status_code, r.text[:300])
                return None
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            return json.loads(text)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print("  AI call failed:", e)
            if isinstance(e, requests.Timeout):
                continue
            time.sleep(5)
    print("  AI gave no usable answer")
    return None


def extract_funding(cands, model):
    """cands: [{'id','company','text'}] -> {id: {...}}"""
    if not cands:
        return {}
    prompt = (
        "You read news headlines about companies and extract funding facts. For each item return an object "
        "with: id, is_funding (true only if the item reports a funding round, valuation, IPO pricing, debt "
        "financing or a stake sale), about_company (true only if that funding or valuation belongs to the named "
        "company itself, not to a customer, partner, brand or other business that merely uses or mentions it), valuation (the company's valuation as a plain number "
        "in units, e.g. 190000000000, or null if the text does not state one), raise_amount (amount raised as a "
        "plain number, or null), currency (ISO code, default USD), status ('closed' if completed or announced as "
        "done, 'reported' if in talks, planned, sought or attributed to sources). Never infer numbers that are "
        "not written in the text. Return JSON: {\"items\": [...]}.\n\nITEMS:\n"
        + json.dumps(cands, ensure_ascii=False)
    )
    res = _call(prompt, model) or {}
    out = {}
    for x in res.get("items", []):
        if x.get("is_funding") and x.get("about_company") and x.get("id"):
            out[x["id"]] = {"valuation": _num(x.get("valuation")), "raise_amount": _num(x.get("raise_amount")),
                            "currency": (x.get("currency") or "USD").upper()[:3], "status": x.get("status")}
    return out


def _num(v):
    try:
        return float(v) if v not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


BRIEF_RULES = (
    "House style, follow exactly: currency codes not symbols (USD 190bn, EUR 12.15, QAR 4.45); units bn, m, tn; "
    "'c.' for approximations; a minus sign for falls. Plain, neutral, factual sentences. Use only facts in the "
    "data; do not speculate about causes that are not in it; no investment advice; no hype words."
)


def write_briefing(digest, model):
    """digest: compact dict of today's facts with item ids. Returns dict or None."""
    prompt = (
        "You write the executive summary of an investment team's daily monitoring report on its portfolio companies, "
        "the Megatron portfolio and its sponsors. Readers are senior executives. Lead with what changed for these "
        "companies and why it matters. Share-price moves are NOT news by themselves: mention them only in the "
        "'markets' line, never in the headline or in 'happened'. " + BRIEF_RULES +
        "\n\nReturn JSON with keys:\n"
        "headline: one line, max 120 characters, naming the one or two most material company developments "
        "(deals, funding, IPOs, results, legal or regulatory action, leadership). No price moves.\n"
        "happened: list of exactly 3 objects {item_id, text, so_what}. text: the development in max 18 words. "
        "so_what: why it matters to an investor in or partner of this company, max 18 words, factual, no hype. "
        "Use only item_id values from the data; pick different companies where possible; never pick a market item.\n"
        "watch: list of 1 to 4 short lines (max 16 words each) on what to watch next: valuation changes or reported "
        "rounds, events in upcoming_7_days that concern these companies or rates, and open situations.\n"
        "markets: one sentence, max 30 words, only about material moves (a holding moving 3% or more, unusual "
        "volume, or an index moving 1.5% or more). If nothing material, say markets were quiet. market_line_hint "
        "shows the facts.\n"
        "top: list of 5 to 8 objects {item_id, why}, ranked from most to least decision-relevant, different "
        "companies where possible, news items only. why: max 22 words.\n"
        "notes: object mapping company name -> 'why it matters' line (max 22 words) for every company that has items.\n"
        "themes: object mapping industry theme name -> one-line takeaway (max 22 words).\n\nDATA:\n"
        + json.dumps(digest, ensure_ascii=False)
    )
    return _call(prompt, model)


def screen_news(items, model, chunk=250):
    """items: [{'id','company','title','source'}] -> {id: reason} for items to DROP. Sent in small batches."""
    drops = {}
    for k in range(0, len(items), chunk):
        part = items[k:k + chunk]
        prompt = (
            "You screen headlines for an investment team's daily monitoring report. For each item decide if it is "
            "specific, material news ABOUT the named company: its deals, funding, results, products, leadership, "
            "strategy, legal or regulatory matters. Drop: consumer or lifestyle stories, individual user or creator "
            "content, spectacle, tutorials, stock-tip or price-target pieces, analyst commentary where the company is "
            "only the commentator, listings, spam, and stories about a different organisation with a similar name or "
            "where the company is incidental. Return JSON {\"items\": [{\"id\": ..., \"keep\": true|false, "
            "\"reason\": short reason if dropped}]}.\n\nITEMS:\n" + json.dumps(part, ensure_ascii=False))
        res = _call(prompt, model, timeout=300) or {}
        for x in res.get("items", []):
            if x.get("id") and x.get("keep") is False:
                drops[x["id"]] = x.get("reason") or "not material"
    return drops

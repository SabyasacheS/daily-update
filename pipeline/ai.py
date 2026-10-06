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


def available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _call(prompt, model, tries=3):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    for i in range(tries):
        try:
            r = requests.post(URL.format(model=model), json=body, timeout=120,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            if r.status_code in (429, 500, 503):
                time.sleep(15 * (i + 1))
                continue
            if r.status_code >= 400:
                print("  AI error", r.status_code, r.text[:300])
                return None
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            return json.loads(text)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print("  AI call failed:", e)
            time.sleep(5)
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
        "You write the morning briefing for an investment team's daily monitoring report. "
        + BRIEF_RULES +
        "\n\nReturn JSON with keys:\n"
        "headline: one line, max 110 characters, naming the 2-3 most important developments.\n"
        "paragraphs: list of 2 paragraphs, each max 85 words. First: the most important company and market "
        "developments. Second: other notable items and macro context.\n"
        "top: list of 5 to 8 objects {item_id, why}, ranked from most to least decision-relevant, about different "
        "companies where possible (use only item_id values present in the data; a market move has an item_id too). "
        "why: max 22 words.\n"
        "notes: object mapping company name -> 'why it matters' line (max 22 words) for every company that has items.\n"
        "themes: object mapping industry theme name -> one-line takeaway (max 22 words).\n\nDATA:\n"
        + json.dumps(digest, ensure_ascii=False)
    )
    return _call(prompt, model)

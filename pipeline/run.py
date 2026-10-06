"""Daily Update pipeline.

    python -m pipeline.run                 # gather, build, publish site; email if it's a send day
    python -m pipeline.run --email no      # refresh the site only (used after watchlist edits)
    python -m pipeline.run --email yes     # force the email
    python -m pipeline.run --fixture tests/fixture.json --email no   # offline test render
"""
import argparse
import os
import time
from datetime import date, timedelta

from . import ai, calendar, history, markets, news, render, valuations
from .config import (EVENTS, STATE, fmt_pct, fmt_price, fmt_ratio, house_style, load_json, load_watchlist,
                     local_now, now_utc, save_json)

PRIVATE_SECTIONS = {"portfolio", "megatron"}


# ---------------------------------------------------------------- gather (network)

def gather(wl, state, today):
    s = wl["settings"]
    win = s.get("news_window_hours", 72)
    raw = {"quotes": {}, "news": {}, "filtered": [], "macro": [], "industry": {}, "valuation_search": {},
           "earnings": {}, "fred": []}

    symbols = [c["ticker"] for c in wl["companies"] if c.get("ticker")] + [b["symbol"] for b in s.get("benchmarks", [])]
    print(f"Prices for {len(symbols)} symbols")
    for sym in symbols:
        raw["quotes"][sym] = markets.fetch_history(sym)
        time.sleep(0.4)  # stay under Yahoo's rate limits

    print(f"News for {len(wl['companies'])} companies")
    for c in wl["companies"]:
        items, filtered = news.company_news(c, win, wl.get("busy_focus", []))
        raw["news"][c["name"]] = items
        raw["filtered"].extend(filtered)

    for q in wl.get("macro", []):
        raw["macro"].extend(news.topic_news(q, win, limit=1))
    for t in wl.get("industry", []):
        items = []
        for q in t.get("queries", []):
            items.extend(news.topic_news(q, win, limit=3))
        raw["industry"][t["name"]] = news.cluster(items, 6)

    checked = state.setdefault("val_checked", {})
    week_ago = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
    for c in wl["companies"]:
        if set(c["sections"]) & PRIVATE_SECTIONS and "public" not in c["sections"] and not c.get("ticker"):
            if checked.get(c["name"], "") < week_ago:
                raw["valuation_search"][c["name"]] = news.valuation_search(c)
                checked[c["name"]] = today

    for c in wl["companies"]:
        if c.get("ticker"):
            raw["earnings"][c["ticker"]] = markets.fetch_earnings_dates(c["ticker"])
    end = (date.fromisoformat(today) + timedelta(days=s.get("calendar_days", 21))).isoformat()
    raw["fred"] = calendar.fred_releases(today, end)
    return raw


# ---------------------------------------------------------------- build (pure apart from AI calls)

def build(wl, raw, state, today, use_ai=True):
    s = wl["settings"]
    thr = s.get("thresholds", {})
    model = os.environ.get("GEMINI_MODEL") or s.get("gemini_model", "gemini-2.5-flash")
    use_ai = use_ai and ai.available()
    section_ids = [x["id"] for x in wl["sections"]]

    # --- quotes
    quotes = {sym: markets.compute_quote(h, thr) for sym, h in raw["quotes"].items() if h}
    benchmarks = []
    for b in s.get("benchmarks", []):
        q = quotes.get(b["symbol"])
        if q:
            benchmarks.append(dict(b, q=q))
    holdings = []
    for c in wl["companies"]:
        if "public" in c["sections"]:
            q = quotes.get(c.get("ticker"))
            holdings.append({"name": c["name"], "ticker": c.get("ticker", ""), "exchange": c.get("exchange", ""),
                             "currency": c.get("currency") or (q or {}).get("currency") or "", "q": q})
    movers = [h for h in holdings if h["q"] and h["q"]["change_pct"] is not None]
    if movers:
        max(movers, key=lambda h: abs(h["q"]["change_pct"]))["largest"] = True

    # --- companies + news
    companies = {}
    for c in wl["companies"]:
        items = [dict(i, title=house_style(i["title"])) for i in raw["news"].get(c["name"], [])]
        companies[c["name"]] = {"name": c["name"], "sections": c["sections"], "ticker": c.get("ticker", ""),
                                "currency": c.get("currency", ""), "domain": c.get("domain", ""),
                                "items": items, "q": quotes.get(c.get("ticker")), "listed": bool(c.get("ticker"))}
    macro = news.cluster([dict(i, title=house_style(i["title"])) for i in raw["macro"]], 8)
    industry = [{"name": t, "items": [dict(i, title=house_style(i["title"])) for i in its]}
                for t, its in raw["industry"].items()]
    every = [i for c in companies.values() for i in c["items"]] + macro + [i for t in industry for i in t["items"]]
    history.mark_new(every, today)

    # --- valuations
    for c in wl["companies"]:
        valuations.seed_from_watchlist(state, c)
    val_changes, signals = [], []
    cand = []
    for c in wl["companies"]:
        if not (set(c["sections"]) & PRIVATE_SECTIONS) or c.get("ticker"):
            continue
        for it in valuations.candidates(raw["news"].get(c["name"], [])):
            cand.append((c["name"], it, True))
        for it in valuations.candidates(raw["valuation_search"].get(c["name"], [])):
            cand.append((c["name"], it, False))
    ai_ext = {}
    if use_ai and cand:
        ai_ext = ai.extract_funding([{"id": f"{n}|{it['id']}", "company": n,
                                      "text": it["title"] + ". " + it.get("snippet", "")} for n, it, _ in cand], model)
    for name, it, recent in sorted(cand, key=lambda x: x[1].get("ts", "")):
        text = it["title"] + ". " + it.get("snippet", "")
        ext = ai_ext.get(f"{name}|{it['id']}") if use_ai else None
        ext = valuations.validate(ext or valuations.regex_extract(text), text)
        if not ext:
            continue
        ch = valuations.apply(state, name, ext, it, today)
        if ch and ch["type"] in ("valuation", "reported"):
            val_changes.append(ch)
        elif ch and ch["type"] == "signal" and recent:
            signals.append(ch)
    for name, comp in companies.items():
        comp["view"] = valuations.card_view(state, name, today)
        comp["signal"] = next((x for x in signals if x["company"] == name), None)

    # --- last known item for quiet companies
    last = state.setdefault("last_item", {})
    for name, comp in companies.items():
        if comp["items"]:
            top = comp["items"][0]
            last[name] = {"title": top["title"], "date": top["date"], "url": top["url"]}
        comp["last"] = last.get(name)

    # --- calendar
    cal = calendar.build(load_json(EVENTS, []), raw.get("fred", []), raw.get("earnings", {}),
                         wl["companies"], today, s.get("calendar_days", 21))

    report = {"today": today, "settings": s, "benchmarks": benchmarks, "holdings": holdings,
              "companies": companies, "macro": macro, "industry": industry, "calendar": cal,
              "sections": [{"id": x["id"], "label": x["label"],
                            "names": [c["name"] for c in wl["companies"] if x["id"] in c["sections"]]}
                           for x in wl["sections"] if x["id"] in section_ids]}

    # --- briefing
    briefing, res = None, None
    if use_ai:
        res = ai.write_briefing(digest(report, val_changes, signals), model)
        briefing = from_ai(res, report) if res else None
    report["briefing"] = briefing or fallback_briefing(report, val_changes, signals)
    report["briefing"]["ai"] = bool(briefing)
    notes = (res or {}).get("notes", {}) if briefing else {}
    themes = (res or {}).get("themes", {}) if briefing else {}
    for name, comp in companies.items():
        comp["why"] = house_style(notes.get(name, "")) if comp["items"] else ""
    for t in industry:
        t["takeaway"] = house_style(themes.get(t["name"], ""))

    report["changes"] = history.diff(report, history.previous_snapshot(today), val_changes, signals, raw["filtered"])
    report["counts"] = {
        "flags": len(report["changes"]["moves"]),
        "valuations": len([v for v in val_changes if v["type"] == "valuation"]),
        "signals": len(signals) + len([v for v in val_changes if v["type"] == "reported"]),
        "with_news": {sec["id"]: sum(1 for n in sec["names"] if companies[n]["items"]) for sec in report["sections"]},
        "new_pr": len(report["changes"]["new_pr"]), "new_news": len(report["changes"]["new_news"]),
    }
    return report


def all_items_by_id(report):
    idx = {}
    for n, c in report["companies"].items():
        for it in c["items"]:
            idx.setdefault(it["id"], dict(it, company=n))
    for it in report["macro"]:
        idx.setdefault(it["id"], dict(it, company=""))
    for t in report["industry"]:
        for it in t["items"]:
            idx.setdefault(it["id"], dict(it, company=t["name"]))
    for h in report["holdings"]:
        q = h["q"]
        if q:
            idx["mkt:" + h["name"]] = {
                "id": "mkt:" + h["name"], "company": h["name"], "kind": "market", "url": "markets.html",
                "title": f"{h['name']} {fmt_pct(q['change_pct'])} to {h['currency']} {fmt_price(q['price'])}",
                "source": h.get("exchange", ""), "date": q["date"], "sources": [h.get("exchange", "")]}
    return idx


def digest(report, val_changes, signals):
    d = {"date": report["today"], "holdings": [], "benchmarks": [], "valuation_changes": val_changes,
         "funding_signals": signals, "companies": [], "macro": [], "themes": {}}
    for h in report["holdings"]:
        q = h["q"]
        if q:
            d["holdings"].append({"item_id": "mkt:" + h["name"], "name": h["name"], "currency": h["currency"],
                                  "price": round(q["price"], 2), "change_pct": round(q["change_pct"] or 0, 2),
                                  "vol_vs_10d": round(q["vs10"] or 0, 2), "vol_vs_3m": round(q["vs3m"] or 0, 2),
                                  "flags": q["flags"]})
    for b in report["benchmarks"]:
        d["benchmarks"].append({"name": b["name"], "value": round(b["q"]["price"], 2),
                                "change_pct": round(b["q"]["change_pct"] or 0, 2)})
    for n, c in report["companies"].items():
        if c["items"]:
            d["companies"].append({"name": n, "sections": c["sections"],
                                   "valuation": c["view"].get("valuation", {}).get("text"),
                                   "items": [{"item_id": i["id"], "title": i["title"], "source": i["source"],
                                              "date": i["date"], "type": i["kind"], "new": i.get("is_new"),
                                              "n_sources": len(i["sources"])} for i in c["items"][:5]]})
    d["macro"] = [{"item_id": i["id"], "title": i["title"], "source": i["source"], "date": i["date"]}
                  for i in report["macro"]]
    d["themes"] = {t["name"]: [{"item_id": i["id"], "title": i["title"]} for i in t["items"]]
                   for t in report["industry"]}
    return d


SECTION_LABEL = {"public": "Markets", "portfolio": "Portfolio", "megatron": "Megatron", "sponsors": "Sponsors"}
SECTION_PAGE = {"public": "markets.html", "portfolio": "portfolio.html", "megatron": "megatron.html",
                "sponsors": "sponsors.html"}


def _label_for(report, it):
    c = report["companies"].get(it.get("company", ""))
    if it.get("kind") == "market":
        return "Markets", "markets.html"
    if c:
        sec = next((s for s in c["sections"] if s != "public"), c["sections"][0] if c["sections"] else "")
        return SECTION_LABEL.get(sec, ""), SECTION_PAGE.get(sec, "index.html")
    return ("Industry", "industry.html") if it.get("company") else ("Macro", "index.html")


def top_entry(report, it, why):
    label, page = _label_for(report, it)
    return {"label": label, "company": it.get("company", ""), "title": house_style(it["title"]), "url": it["url"],
            "page": page, "source": ", ".join(it.get("sources", [it.get("source", "")])[:3]),
            "date": it.get("date", ""), "why": house_style(why or "")}


def from_ai(res, report):
    idx = all_items_by_id(report)
    top = []
    for t in res.get("top3", []):
        it = idx.get(t.get("item_id"))
        if it and all(x["title"] != it["title"] for x in top):
            top.append(top_entry(report, it, t.get("why")))
    paras = [house_style(p) for p in res.get("paragraphs", []) if p][:2]
    if not res.get("headline") or not paras:
        return None
    if len(top) < 3:
        for e in fallback_top(report, [], []):
            if len(top) >= 3:
                break
            if all(x["title"] != e["title"] for x in top):
                top.append(e)
    return {"headline": house_style(res["headline"]), "paragraphs": paras, "top3": top[:3]}


def fallback_top(report, val_changes, signals):
    idx = all_items_by_id(report)
    scored = []
    for h in report["holdings"]:
        q = h["q"]
        if q and q["flags"]:
            why = (f"Volume {fmt_ratio(q['vs10'])} its 10-day and {fmt_ratio(q['vs3m'])} its 3-month average."
                   if q["vs10"] and q["vs3m"] else "")
            scored.append((3 + abs(q["change_pct"] or 0) / 3, idx["mkt:" + h["name"]], why))
    for v in val_changes:
        it = {"title": f"{v['company']} valuation {v['to']}" + (" (reported)" if v["type"] == "reported" else ""),
              "url": v["source_url"], "company": v["company"], "source": "", "date": v["date"], "kind": "news"}
        scored.append((6, it, f"Previously {v['from']}." if v.get("from") else ""))
    for sgl in signals:
        raise_txt = f"Raise of {sgl['raise_text']} " if sgl.get("raise_text") else "New round "
        scored.append((5, {"title": sgl["source_title"], "url": sgl["source_url"], "company": sgl["company"],
                           "source": sgl.get("source", ""), "date": sgl["date"], "kind": "news"},
                       raise_txt + ("reported, not confirmed; valuation on file unchanged." if sgl["status"] != "closed"
                                    else "announced; no valuation stated.")))
    for n, c in report["companies"].items():
        for i in c["items"]:
            if i.get("is_new"):
                scored.append((1.5 + 0.4 * len(i["sources"]) + (0.5 if i["kind"] == "pr" else 0), dict(i, company=n), ""))
    out, used = [], set()
    for _, it, why in sorted(scored, key=lambda x: -x[0]):
        if it.get("company") in used:
            continue
        used.add(it.get("company"))
        out.append(top_entry(report, it, why))
        if len(out) == 3:
            break
    return out


def fallback_briefing(report, val_changes, signals):
    top = fallback_top(report, val_changes, signals)
    parts = []
    for h in report["holdings"]:
        q = h["q"]
        if q:
            parts.append(f"{h['name']} {fmt_pct(q['change_pct'])} at {h['currency']} {fmt_price(q['price'])}")
    p1 = ("Holdings: " + "; ".join(parts) + ".") if parts else ""
    n_news = sum(1 for x in report["companies"].values() if x["items"])
    p2 = f"{n_news} of {len(report['companies'])} tracked names had news in the last 72 hours."
    if val_changes:
        p2 += " Valuation updates: " + "; ".join(f"{v['company']} {v['to']}" for v in val_changes) + "."
    headline = "; ".join(t["title"] for t in top[:2]) or f"Daily Update for {report['today']}"
    return {"headline": headline[:140], "paragraphs": [p for p in (p1, p2) if p], "top3": top}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", choices=["auto", "yes", "no"], default="auto")
    ap.add_argument("--fixture", help="offline test: load raw data from a JSON file")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    wl = load_watchlist()
    s = wl["settings"]
    state = load_json(STATE, {})
    local = local_now(s)
    today = local.date().isoformat()

    if args.fixture:
        fx = load_json(args.fixture, {})
        raw = fx["raw"]
        today = fx.get("today", today)
    else:
        raw = gather(wl, state, today)

    report = build(wl, raw, state, today, use_ai=not args.no_ai)
    report["generated_local"] = local.strftime("%d %b %Y, %H:%M ") + s.get("timezone_label", "AST")
    report["generated_utc"] = now_utc().strftime("%Y-%m-%d %H:%M UTC")

    render.site(report, wl)
    save_json(STATE, state)
    history.save_snapshot(today, report)
    print("Site written to docs/")

    send = args.email == "yes" or (args.email == "auto" and local.strftime("%a") in s.get("send_days", [])
                                   and state.get("last_email") != today)
    if send:
        from . import mailer
        html = render.email_html(report, wl)
        pdf = render.pdf_bytes(report, wl) if s.get("attach_pdf", True) else None
        if mailer.send(report, wl, html, pdf):
            state["last_email"] = today
            save_json(STATE, state)
    else:
        print("Email not sent (not a send day, already sent today, or --email no)")


if __name__ == "__main__":
    main()

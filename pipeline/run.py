"""Daily Update pipeline.

    python -m pipeline.run                 # gather, build, publish site; email if it's a send day
    python -m pipeline.run --email no      # refresh the site only (used after watchlist edits)
    python -m pipeline.run --email yes     # force the email
    python -m pipeline.run --fixture tests/fixture.json --email no   # offline test render
"""
import argparse
import re
import os
import time
from datetime import date, timedelta

from . import ai, calendar, history, markets, news, relevance, render, valuations
from .config import (EVENTS, STATE, VALUATIONS, fmt_pct, fmt_price, fmt_ratio, house_style, load_json, load_watchlist,
                     local_now, now_utc, save_json)

PRIVATE_SECTIONS = {"portfolio", "megatron"}


# ---------------------------------------------------------------- gather (network)

def gather(wl, state, today):
    s = wl["settings"]
    win = s.get("news_window_hours", 72)
    raw = {"quotes": {}, "news": {}, "earlier": {}, "filtered": [], "macro": [], "industry": {}, "valuation_search": {},
           "earnings": {}, "fred": []}

    symbols = [c["ticker"] for c in wl["companies"] if c.get("ticker")] + [b["symbol"] for b in s.get("benchmarks", [])]
    print(f"Prices for {len(symbols)} symbols")
    for sym in symbols:
        raw["quotes"][sym] = markets.fetch_history(sym)
        time.sleep(0.4)  # stay under Yahoo's rate limits

    print(f"News for {len(wl['companies'])} companies")
    for c in wl["companies"]:
        items, filtered, earlier = news.company_news(c, win, wl.get("busy_focus", []))
        raw["news"][c["name"]] = items
        raw["earlier"][c["name"]] = earlier
        raw["filtered"].extend(filtered)

    for m in wl.get("macro", []):
        q, must = (m, None) if isinstance(m, str) else (m["query"], m.get("must"))
        raw["macro"].extend(news.topic_news(q, win, limit=1, must=must))
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

    # --- AI second check on company news (only when a Gemini key is set)
    if use_ai:
        batch = [{"id": f"{n}|{i['id']}", "company": n, "title": i["title"], "source": i["source"]}
                 for n, its in raw["news"].items() for i in its]
        drops = ai.screen_news(batch, model) if batch else {}
        for n in list(raw["news"]):
            keep = []
            for i in raw["news"][n]:
                why = drops.get(f"{n}|{i['id']}")
                if why:
                    raw["filtered"].append({"company": n, "title": i["title"], "reason": "AI: " + why})
                else:
                    keep.append(i)
            raw["news"][n] = keep

    # --- companies + news
    companies = {}
    for c in wl["companies"]:
        items = [dict(i, title=house_style(i["title"])) for i in raw["news"].get(c["name"], [])]
        companies[c["name"]] = {"name": c["name"], "sections": c["sections"], "ticker": c.get("ticker", ""),
                                "currency": c.get("currency", ""), "domain": c.get("domain", ""),
                                "items": items, "q": quotes.get(c.get("ticker")), "listed": bool(c.get("ticker")),
                                "earlier": [dict(i, title=house_style(i["title"]))
                                            for i in raw.get("earlier", {}).get(c["name"], [])]}
    macro = news.cluster([dict(i, title=house_style(i["title"])) for i in raw["macro"]], 8)
    industry = [{"name": t, "items": [dict(i, title=house_style(i["title"])) for i in its]}
                for t, its in raw["industry"].items()]
    every = [i for c in companies.values() for i in c["items"]] + macro + [i for t in industry for i in t["items"]]
    history.mark_new(every, today)

    # --- valuations
    valuations.seed_all(state, wl["companies"], {k: v for k, v in load_json(VALUATIONS, {}).items()
                                                 if not k.startswith("_")})
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
    aliases = {c["name"]: c["aliases"] for c in wl["companies"]}
    for name, it, recent in sorted(cand, key=lambda x: x[1].get("ts", "")):
        text = it["title"] + ". " + it.get("snippet", "")
        if use_ai:
            ext = ai_ext.get(f"{name}|{it['id']}")  # only items the AI says are about this company's own funding
        else:
            ext = valuations.regex_extract(text) if valuations.is_subject(it["title"], aliases[name]) else None
        ext = valuations.validate(ext, text)
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
    if state.get("last_item_v", 1) < 3:  # entries saved before the current relevance filter
        state["last_item"] = {}
        state["last_item_v"] = 3
    last = state.setdefault("last_item", {})
    for name, comp in companies.items():
        if comp["items"]:
            top = comp["items"][0]
            last[name] = {"title": top["title"], "date": top["date"], "url": top["url"]}
        prev = last.get(name)
        if prev and relevance.topic_junk(prev.get("title", ""), ""):
            last.pop(name, None)  # stored before the stricter filter existed
            prev = None
        comp["last"] = prev

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
        briefing = from_ai(res, report, val_changes, signals) if res else None
        print("  AI briefing:", "used" if briefing else ("unusable answer: " + str(res)[:200] if res else "no answer"))
    report["briefing"] = briefing or fallback_briefing(report, val_changes, signals)
    report["briefing"]["ai"] = bool(briefing)
    used = {h["orig"] for h in report["briefing"].get("happened", [])}
    report["briefing"]["key"] = [t for t in report["briefing"].get("key", []) if t["title"] not in used][:5]
    report["briefing"]["also"] = also_today(report)
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


def also_today(report, n=5):
    """Other new stories worth a glance: one per company, not already in Key news, most widely covered first."""
    shown = {t["title"] for t in report["briefing"].get("key") or report["briefing"].get("top3") or []}
    shown |= {h["orig"] for h in report["briefing"].get("happened", [])}
    shown_co = {t.get("company") for t in report["briefing"].get("key") or []} | \
        {h["company"] for h in report["briefing"].get("happened", [])}
    pool = []
    for name, c in report["companies"].items():
        for it in c["items"]:
            if it.get("is_new") and it["title"] not in shown:
                pool.append(dict(it, company=name))
    pool.sort(key=lambda i: (len(i["sources"]), i["kind"] == "pr", i.get("ts", "")), reverse=True)
    out, used = [], set(shown_co)
    for it in pool:
        if it["company"] in used:
            continue
        used.add(it["company"])
        out.append(it)
        if len(out) == n:
            break
    return out


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
    d["upcoming_7_days"] = [{"date": e["date"], "event": e["title"], "detail": e.get("detail", "")}
                            for e in report["calendar"] if e["days_away"] <= 7]
    d["reported_valuations"] = [{"company": n, "reported": c["view"]["reported"]["text"],
                                 "kind": c["view"]["reported"]["label"]}
                                for n, c in report["companies"].items() if c["view"].get("reported")]
    d["market_line_hint"] = markets_line(report)
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


def split_ranked(ranked):
    """Top 3 for the site and PDF; ranked news items (market moves excluded, they are in the holdings table)."""
    return {"top3": ranked[:3], "key": [t for t in ranked if t["label"] != "Markets"][:8]}


def happened_entry(report, it, text=None, so_what=""):
    label, page = _label_for(report, it)
    t = house_style(text or it["title"])
    co = it.get("company", "")
    return {"label": label, "company": co, "show_co": not t.lower().startswith(co.lower().split()[0]) if co else False,
            "text": t, "orig": house_style(it["title"]),
            "so_what": house_style(so_what or ""), "url": it["url"] if it["url"].startswith("http") else page,
            "source": ", ".join(it.get("sources", [it.get("source", "")])[:2]), "date": it.get("date", "")}


def from_ai(res, report, val_changes=(), signals=()):
    idx = all_items_by_id(report)
    ranked = []
    for t in res.get("top") or []:
        it = idx.get(t.get("item_id"))
        if it and all(x["title"] != house_style(it["title"]) for x in ranked):
            ranked.append(top_entry(report, it, t.get("why")))
    happened = []
    for h in res.get("happened") or []:
        it = idx.get(h.get("item_id"))
        if it and h.get("text"):
            happened.append(happened_entry(report, it, h["text"], h.get("so_what")))
    if not res.get("headline") or not happened:
        return None
    for e in fallback_top(report, [], [], n=8):
        if len(ranked) >= 8:
            break
        if all(x["title"] != e["title"] for x in ranked):
            ranked.append(e)
    watch = [house_style(w) for w in (res.get("watch") or []) if w][:4] or watch_list(report, val_changes, signals)
    return dict({"headline": house_style(res["headline"]), "happened": happened[:3], "watch": watch,
                 "markets": house_style(res.get("markets") or markets_line(report))}, **split_ranked(ranked))


def markets_line(report, move=3.0, index_move=1.5):
    """One sentence, only about moves that matter."""
    bits = []
    for h in report["holdings"]:
        q = h["q"]
        if not q or q["change_pct"] is None:
            continue
        big = abs(q["change_pct"]) >= move
        vol = "volume" in q["flags"]
        if big or vol:
            verb = "rose" if q["change_pct"] > 0 else "fell"
            t = f"{h['name']} {verb} {abs(q['change_pct']):.1f}%"
            if vol:
                t += f" on {fmt_ratio(q['vs10'])} its usual volume"
            bits.append(t)
    for b in report["benchmarks"]:
        q = b["q"]
        if b.get("unit") != "yield" and q.get("change_pct") is not None and abs(q["change_pct"]) >= index_move:
            verb = "rose" if q["change_pct"] > 0 else "fell"
            bits.append(f"{b['name']} {verb} {abs(q['change_pct']):.1f}%")
    if not bits:
        return f"Markets were quiet: no holding moved more than {move:.0f}%."
    return "; ".join(bits[:4]) + "."


def watch_list(report, val_changes, signals, days=7):
    out = []
    for v in val_changes:
        if v["type"] == "valuation":
            out.append(f"{v['company']} valuation updated to {v['to']}" + (f" (was {v['from']})." if v.get("from") else "."))
        else:
            out.append(f"{v['company']}: new valuation of {v['to']} reported, not confirmed.")
    for sg in signals:
        amt = f" of {sg['raise_text']}" if sg.get("raise_text") else ""
        state = "reported, not confirmed" if sg["status"] != "closed" else "announced, no valuation stated"
        out.append(f"{sg['company']}: funding round{amt} {state}.")
    for e in report["calendar"]:
        if e["days_away"] <= days:
            when = "today" if e["days_away"] == 0 else ("tomorrow" if e["days_away"] == 1 else f"{e['weekday']} {e['day']}")
            out.append(f"{e['title']} {when}.")
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq[:4]


MATERIAL = re.compile(
    r"\b(rais\w*|funding|round|valuation|valued|ipo|listing|s-1|acquir\w*|acquisition|merger|buyout|take-private|"
    r"deal|stake|sells?|sale|divest\w*|lawsuit|sues?|sued|court|settle\w*|fine[ds]?|penalt\w*|ban\w*|probe|"
    r"investigat\w*|regulat\w*|antitrust|sanction\w*|results|earnings|revenue|profit|loss(es)?|guidance|"
    r"layoffs?|ceo|cfo|resign\w*|steps? down|appoint\w*|hack\w*|breach|bankrupt\w*|default|margin calls?|"
    r"debt|bonds?|loans?|credit|fund(raise|raising)?|closes?|blacklist\w*|pentagon|government|contract)\b", re.I)


def fallback_top(report, val_changes, signals, n=3):
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
                material = bool(MATERIAL.search(i["title"]))
                score = 1.0 + 0.5 * min(len(i["sources"]), 4) + (2.5 if material else 0) - (0.5 if i["kind"] == "pr" and not material else 0)
                scored.append((score, dict(i, company=n), ""))
    out, used = [], set()
    for _, it, why in sorted(scored, key=lambda x: -x[0]):
        k = (it.get("company"), it.get("kind") == "market")  # a company can have one price move and one news item
        if k in used:
            continue
        used.add(k)
        out.append(top_entry(report, it, why))
        if len(out) == n:
            break
    return out


def fallback_briefing(report, val_changes, signals):
    ranked = fallback_top(report, val_changes, signals, n=10)
    news = [t for t in ranked if t["label"] != "Markets"]
    idx = all_items_by_id(report)
    happened = []
    for t in news[:3]:
        it = next((i for i in idx.values() if i.get("title") and house_style(i["title"]) == t["title"]),
                  {"title": t["title"], "url": t["url"], "company": t["company"], "source": t["source"], "date": t["date"]})
        happened.append(happened_entry(report, dict(it, company=t["company"]), t["title"], t.get("why")))
    if news:
        headline = news[0]["title"]
        if len(news) > 1 and len(headline) + len(news[1]["title"]) < 130:
            headline += "; " + news[1]["title"]
    else:
        headline = "No major company developments today"
    return dict({"headline": headline[:160], "happened": happened, "watch": watch_list(report, val_changes, signals),
                 "markets": markets_line(report)}, **split_ranked(ranked))


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

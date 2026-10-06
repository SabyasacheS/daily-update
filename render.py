"""Turns the report into the website (docs/), the email HTML and the PDF."""
import os
import re
import shutil
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import (DOCS, MINUS, TEMPLATES, WATCHLIST, fmt_date_short, fmt_pct, fmt_price, fmt_ratio,
                     fmt_vol_m)

NAV = [("briefing", "Briefing", "index.html"), ("changed", "What changed", "changed.html"),
       ("markets", "Markets", "markets.html"), ("industry", "Industry", "industry.html"),
       ("portfolio", "Portfolio", "portfolio.html"), ("megatron", "Megatron", "megatron.html"),
       ("sponsors", "Sponsors", "sponsors.html"), ("calendar", "Calendar", "calendar.html"),
       ("sources", "Sources", "sources.html")]


def _longdate(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%A %d %b %Y")
    except (TypeError, ValueError):
        return iso or ""


def _bps(x):
    if x is None:
        return "n/a"
    v = round(x * 100)
    return f"{'+' if v > 0 else (MINUS if v < 0 else '')}{abs(v)} bp"


def env():
    e = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]),
                    trim_blocks=True, lstrip_blocks=True)
    e.filters.update(price=fmt_price, pct=fmt_pct, ratio=fmt_ratio, volm=fmt_vol_m, shortdate=fmt_date_short,
                     longdate=_longdate, bps=_bps, slug=lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-"))
    return e


def _nav(report):
    ids = {s["id"] for s in report["sections"]}
    return [n for n in NAV if n[0] not in ("portfolio", "megatron", "sponsors") or n[0] in ids]


def _pages(report):
    pages = [("index.html", "briefing.html", "briefing", "Briefing", {}),
             ("changed.html", "changed.html", "changed", "What changed", {}),
             ("markets.html", "markets.html", "markets", "Markets", {}),
             ("industry.html", "industry.html", "industry", "Industry", {})]
    for sec in report["sections"]:
        if sec["id"] != "public":
            pages.append((f"{sec['id']}.html", "companies.html", sec["id"], sec["label"], {"sec": sec}))
    pages += [("calendar.html", "calendar.html", "calendar", "Calendar", {}),
              ("sources.html", "sources.html", "sources", "Sources", {})]
    return pages


def site(report, wl):
    e = env()
    today = report["today"]
    s = report["settings"]
    nav = _nav(report)
    arch = os.path.join(DOCS, "archive", today)
    os.makedirs(arch, exist_ok=True)
    base = dict(r=report, s=s, nav=nav)
    for out, tpl, key, title, extra in _pages(report):
        t = e.get_template(tpl)
        html = t.render(root="", site_root="", page=key, title=title, **base, **extra)
        with open(os.path.join(DOCS, out), "w", encoding="utf-8") as f:
            f.write(html)
        html = t.render(root="../../", site_root="../../", page=key, title=title, **base, **extra)
        with open(os.path.join(arch, out), "w", encoding="utf-8") as f:
            f.write(html)
    dates = sorted((d for d in os.listdir(os.path.join(DOCS, "archive"))
                    if re.match(r"\d{4}-\d{2}-\d{2}$", d)), reverse=True)
    with open(os.path.join(DOCS, "archive.html"), "w", encoding="utf-8") as f:
        f.write(e.get_template("archive.html").render(root="", site_root="", page="archive", title="Archive",
                                                       dates=dates, **base))
    with open(os.path.join(DOCS, "watchlist.html"), "w", encoding="utf-8") as f:
        f.write(e.get_template("watchlist.html").render(root="", site_root="", page="watchlist",
                                                         title="Watchlist", **base))
    shutil.copyfile(WATCHLIST, os.path.join(DOCS, "watchlist.json"))
    open(os.path.join(DOCS, ".nojekyll"), "w").close()


def email_html(report, wl):
    return env().get_template("email.html").render(r=report, s=report["settings"])


def pdf_bytes(report, wl):
    try:
        from weasyprint import HTML
    except ImportError:
        print("  PDF skipped: weasyprint not installed")
        return None
    try:
        html = env().get_template("pdf.html").render(r=report, s=report["settings"])
        return HTML(string=html, base_url=DOCS).write_pdf()
    except Exception as ex:  # never let the PDF block the email
        print("  PDF failed:", ex)
        return None

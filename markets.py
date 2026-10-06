"""Prices, volumes and earnings dates via yfinance (free, covers Nasdaq, Euronext and the Qatar exchange).

fetch_* functions touch the network; compute_* functions are pure so they can be tested offline.
"""
from datetime import date, datetime


def fetch_history(symbol):
    """Returns {'dates': [...], 'closes': [...], 'volumes': [...], 'currency': str|None} or None."""
    import yfinance as yf
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="6mo", interval="1d", auto_adjust=False)
        h = h.dropna(subset=["Close"])
        if h.empty:
            print("  no price history for", symbol)
            return None
        cur = None
        try:
            cur = t.fast_info.get("currency")
        except Exception:
            pass
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in h.index],
            "closes": [float(x) for x in h["Close"]],
            "volumes": [float(x) if x == x else 0.0 for x in h["Volume"]],
            "currency": cur,
        }
    except Exception as e:  # yfinance raises many kinds of errors
        print("  price fetch failed for", symbol, e)
        return None


def fetch_earnings_dates(symbol):
    """Upcoming earnings dates as ISO strings (may be empty, coverage varies by exchange)."""
    import yfinance as yf
    try:
        cal = yf.Ticker(symbol).calendar
        raw = []
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or []
        elif cal is not None and hasattr(cal, "loc"):
            try:
                raw = list(cal.loc["Earnings Date"])
            except Exception:
                raw = []
        out = []
        for d in raw if isinstance(raw, (list, tuple)) else [raw]:
            if isinstance(d, (date, datetime)):
                out.append(d.strftime("%Y-%m-%d"))
            elif hasattr(d, "strftime"):
                out.append(d.strftime("%Y-%m-%d"))
        return sorted(set(out))
    except Exception as e:
        print("  earnings lookup failed for", symbol, e)
        return []


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def sparkline_points(closes, width=120, height=28):
    pts = closes[-30:]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = width / (len(pts) - 1)
    return " ".join(f"{i * step:.1f},{height - (p - lo) / span * height:.1f}" for i, p in enumerate(pts))


def compute_quote(hist, thresholds):
    """From raw history to the numbers shown on the Markets page."""
    if not hist or len(hist["closes"]) < 2:
        return None
    c, v = hist["closes"], hist["volumes"]
    last, prev = c[-1], c[-2]
    change = last - prev
    pct = change / prev * 100 if prev else None
    vol = v[-1]
    avg10 = _mean(v[-11:-1])
    avg3m = _mean(v[-64:-1])
    vs10 = vol / avg10 if avg10 else None
    vs3m = vol / avg3m if avg3m else None
    flags = []
    if pct is not None and abs(pct) >= thresholds.get("price_move_pct", 3):
        flags.append("price")
    if vs10 and vs3m and vs10 >= thresholds.get("volume_vs_10d", 1.5) and vs3m >= thresholds.get("volume_vs_3m", 1.2):
        flags.append("volume")
    m1 = (last / c[-22] - 1) * 100 if len(c) >= 22 and c[-22] else None
    return {
        "date": hist["dates"][-1], "price": last, "prev": prev, "change": change, "change_pct": pct,
        "volume": vol, "avg10": avg10, "avg3m": avg3m, "vs10": vs10, "vs3m": vs3m,
        "change_1m_pct": m1, "flags": flags, "spark": sparkline_points(c), "currency": hist.get("currency"),
    }

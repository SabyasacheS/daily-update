"""Builds tests/fixture.json: SYNTHETIC price histories ending at real 05 Oct 2026 closes, plus real headlines.
Only for offline rendering tests:
    python tests/make_fixture.py
    python -m pipeline.run --fixture tests/fixture.json --email no --no-ai
"""
import hashlib, json, random
random.seed(1)

def hist(last, prev, vol, avg10, avg3m, n=70):
    closes = [prev * (1 + random.uniform(-0.03, 0.03)) for _ in range(n - 2)] + [prev, last]
    vols = [avg3m * 1e6 * random.uniform(0.8, 1.2) for _ in range(n - 11)] + [avg10 * 1e6] * 10 + [vol * 1e6]
    dates = [f"2026-{7 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n - 1)] + ["2026-10-05"]
    return {"dates": dates, "closes": closes, "volumes": vols, "currency": None}

def it(title, source, date, kind="news", url="https://news.google.com/"):
    x = {"title": title, "url": url, "source": source, "date": date, "ts": date + "T08:00:00+00:00",
         "kind": kind, "sources": [source]}
    x["id"] = hashlib.sha1(title.lower().encode()).hexdigest()[:12]
    return x

news = {
 "SpaceX": [it("SpaceX stock climbs to highest since June, returning Musk to trillionaire status", "CNBC", "2026-10-05"),
            it("SDA's Fourth Tranche 1 Mission", "SpaceX", "2026-10-06", "pr")],
 "OpenAI": [it("OpenAI looks to UAE for up to $10 billion as it lines up $30 billion round; BlackRock in talks", "Moneycontrol", "2026-10-06"),
            it("OpenAI executive Jason Kwon to face grilling at parliament about AI and Australians' private data", "The Guardian", "2026-10-05"),
            it("Our approach to EU text provenance rules", "OpenAI", "2026-10-05", "pr")],
 "Anthropic": [it("Pentagon stops using Anthropic AI tools after blacklisting company, BBC told", "BBC", "2026-10-05")],
 "Databricks": [it("NOL Universe Unifies Global Data", "Databricks", "2026-10-05", "pr"),
                it("NEAREST BY Join: Scaling Vector Search in Databricks Runtime", "Databricks", "2026-10-05", "pr")],
 "TikTok US": [it("TikTok agrees to pay at least $100M in Alabama teen safety deal", "Top Class Actions", "2026-10-05"),
               it("TikTok unveils AI-powered updates for advertisers", "TikTok Newsroom", "2026-10-05", "pr")],
 "Binance": [it("Binance launches retail AI assistant, repackages existing trading tools", "Finance Magnates", "2026-10-05")],
 "Vantage Data Centers NA": [it("Vantage data center opponents push misleading claims on jobs", "Milwaukee Journal Sentinel", "2026-10-05")],
}
raw = {
 "quotes": {"SPCX": hist(171.09, 158.96, 132.73, 76.11, 92.79), "BEEMA.QA": hist(4.45, 4.65, 0.28, 0.04, 0.87),
            "BZAI": hist(0.43, 0.48, 2.81, 1.95, 4.51), "CVC.AS": hist(12.15, 12.24, 0.87, 0.92, 1.02)},
 "news": news,
 "filtered": [{"company": "Binance", "title": "Word of the Day: Test Your Knowledge", "reason": "not a news item"},
              {"company": "TikTok US", "title": "ByteDance", "reason": "title too short to be news"}],
 "macro": [it("Federal Reserve interest rate decision looms as inflation worries persist", "Fox Business", "2026-10-05"),
           it("U.S. CFTC joins SEC in proposing crypto regulations, though spot-market gap lingers", "CoinDesk", "2026-10-05")],
 "industry": {"Private Credit / BDC": [], "Tech / AI": [it("AI Infrastructure's Next Phase: Capital, Power and the Right to Build", "Data Center Frontier", "2026-10-05")]},
 "valuation_search": {}, "earnings": {"BX": ["2026-10-22"]}, "fred": [],
}
json.dump({"today": "2026-10-06", "raw": raw}, open("tests/fixture.json", "w"), indent=1)
print("fixture written")

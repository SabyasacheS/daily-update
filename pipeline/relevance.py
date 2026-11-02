"""Decides whether a headline is real company news worth an executive's time.

A story is kept only if it passes every rule:
  1. not spam, clickbait, a quote/listing page or an evergreen web page;
  2. not from a low-quality source (SEO stock sites, content farms, hijacked sites);
  3. the company is the subject (named near the start, not as an analyst, a tool or a backdrop);
  4. it is about business: deals, money, results, products, people, legal or regulatory matters.
Official releases from the company's own site skip rules 3-4 but must still read like an announcement.
"""
import re

SPAM = re.compile(
    r"([\U0001F300-\U0001FAFF☀-➿])|(\+\+|!!|\*NEW|XXX|18\+|\bMMS\b|viral video|original link|hot models|"
    r"full video|leaked|watch ?live|live stream(ing)? free|\bvs\.? .{0,30}\blive\b|\[|\$\+|onlyfans|\bclips?\b\+)", re.I)

NOT_NEWS = re.compile(
    r"\b(careers?|jobs? at|job openings?|we'?re hiring|internship|candidate|cookie|privacy policy|terms of (use|service)|"
    r"sign ?in|log ?in|my ?account|dashboard|documentation|docs|datasheet|download|installation|licensing|"
    r"word of the day|quiz|giveaway|airdrop|presale|price prediction|coupon|promo code|horoscope|lyrics|"
    r"stock price|share price|stock quote|stock forum|discussion|options chain|price targets?|stock forecasts?|"
    r"forecast & price|shares shorted|short interest|stake (raised|lowered|cut|trimmed|boosted)|"
    r"shares (newly )?(bought|sold|acquired) by|position in|holdings? (in|of)|price to book|p/b|dividend stocks?|"
    r"stocks? (to|retirees|for)|is it a buy|buy or sell|undervalued|a bargain|garp|technical analysis|"
    r"what you need to know|fresh attention|for sale|used -|photos?:|in pictures|watch live|how to watch|"
    r"live stream|livestream|tickets|preview\b|tournament|football|basketball|field hockey|cross country|"
    r"soccer|volleyball|wrestling|theater|theatre|broadway|recipe|explained in|beginner'?s guide|^how to|bull case|bear case|learn why|here'?s why|should you|monthly distribution|net asset value|(raises|cuts|lowers|lifts|adjusts|boosts|trims) (its )?(price )?target|^\d+ .{0,40}\bstocks\b|retirees|collects usd|analysts? (target|see|rate|offer)|passive income|"
    r"lights up the sky|night sky|glowing|jellyfish|stargaz\w*|visible from|spotted over|stunning|"
    r"strangest|weirdest|fun facts?|you won'?t believe|marital|wife|husband|horoscope)\b",
    re.I)

LOW_QUALITY_SOURCES = (
    "tech-insider", "kalkine", "issuewire", "universidad", "university", "college", "marketbeat",
    "gurufocus", "simply wall", "chartmill", "tradingkey", "stocktwits", "pluang", "moomoo", "quiver", "24/7 wall",
    "motley fool", "tradingview", "github", "bigo", "biggo", "insidermonkey", "zacks", "benzinga pro",
    "investorsobserver", "stockstory", "finviz", "barchart", "bitget", "yellow.com", "onesafe", "maxpreps", "guns.com", "gazeta", "britannica", "wikipedia", "linkedin",
    "the dark side", "youtube", "facebook", "instagram", "reddit", "x.com", "medium.com", "blogspot", "substack", "devdiscourse",
    )

BUSINESS = re.compile(
    r"\b(raises?|raised|raising|funding|financing|round|valuation|valued|invest\w*|stake|ipo|listing|s-1|"
    r"acquir\w*|acquisitions?|mergers?|merge|buyouts?|take-private|deals?|agreements?|partner\w*|joint venture|"
    r"team(s)? up|contracts?|orders?|award\w*|wins?|bids?|sales?|sells?|sold|divest\w*|spin-?off|carve[- ]out|"
    r"run-rate|legal|allegations?|espionage|security|breach|hack\w*|robots?|humanoid|demo|ads?|advertis\w*|"
    r"talent|poach\w*|lawyers?|complet\w*|review|audit|shut\w*( down)?|closing|exit\w*|wind(s|ing)? down|"
    r"revenue|sales|earnings|results|profit|loss|guidance|outlook|quarter|q[1-4]|dividend|buyback|"
    r"debt|bond|loan|credit|facility|refinanc\w*|notes?|fund(raise|raising)?|closes?|closed|aum|assets|"
    r"launch\w*|unveil\w*|introduc\w*|releases?|rolls? out|expand\w*|opens?|plans?|build\w*|capacity|"
    r"data cent(er|re)s?|chips?|model|platform|product|customers?|users?|subscribers?|market share|"
    r"ceo|cfo|chair\w*|executive|appoint\w*|hires?|names?|steps? down|resign\w*|leadership|board|layoffs?|"
    r"cuts?|jobs|staff|workforce|lawsuit|sues?|sued|court|judge|ruling|settle\w*|fine[ds]?|penalt\w*|"
    r"regulat\w*|probe|investigat\w*|antitrust|ftc|sec|doj|ban|banned|approval|approved|license|"
    r"export|tariff|sanction\w*|government|pentagon|congress|parliament|policy|rules?|strategy|"
    r"shares|stock|nasdaq|nyse|rally|slump|surge|plunge|soar\w*|tumbl\w*|jumps?|falls?|drops?|"
    r"reverse (stock )?split|delist\w*|restructur\w*|bankrupt\w*|spending|capex|deploy\w*|announc\w*)\b",
    re.I)

# The company is named, but as the one giving an opinion or a rating on someone else.
ANALYST_VOICE = re.compile(
    r"\b(raises|cuts|lowers|adjusts|lifts|trims|maintains|reiterates|initiates|upgrades|downgrades)\b.{0,25}\b"
    r"(target|rating|price objective|coverage)\b|\b(says|sees|expects|warns|forecasts|predicts|on \")", re.I)

# Words that make a busy firm's own-name mention a passing reference.
PASSING = re.compile(r"\b(like|than|rival(s)?|vs\.?|versus|including|such as|uses?|using|built on|powered by)\b", re.I)

ANNOUNCE = re.compile(
    r"\b(announc\w*|introduc\w*|launch\w*|unveil\w*|releas\w*|complet\w*|clos(es|ed|ing)|acquir\w*|agrees?|"
    r"enters?|signs?|appoint\w*|names?|joins?|promot\w*|reports?|declar\w*|prices?|priced|raises?|secures?|"
    r"expand\w*|partner\w*|opens?|invests?|commits?|selects?|awarded|wins?|files?|sells?|to (acquire|sell|buy)|"
    r"now available|generally available|results|record)\b", re.I)

PR_BAD = re.compile(r"^(?:[A-Z][a-z]+ ){1,2}[A-Z][a-z]+(?: - .+)?$")  # a person's name, e.g. "Sara Caceres Sanz"


def _norm(s):
    return (s or "").lower()


def low_quality_source(source):
    s = _norm(source)
    return any(b in s for b in LOW_QUALITY_SOURCES)


def name_position(title, aliases):
    """Word index where the first alias appears, or None."""
    words = re.findall(r"\S+", title)
    low = [w.lower().strip("'\"“”‘’:,.()[]") for w in words]
    best = None
    for a in aliases:
        if not a:
            continue
        aw = a.lower().split()
        for i in range(len(low) - len(aw) + 1):
            if all(low[i + j].startswith(aw[j]) for j in range(len(aw))):
                best = i if best is None else min(best, i)
                break
    return best


def judge(title, source, company, is_pr):
    """Returns None if the item is relevant, otherwise a short reason it was dropped."""
    t = title.strip()
    if SPAM.search(t):
        return "spam"
    if NOT_NEWS.search(t):
        return "not company news"
    if len(t.split()) < 4:
        return "page title, not news"
    if is_pr:
        if PR_BAD.match(t) or re.search(r"\s-\s[A-Z][\w &.]+$", t):  # people bios, "Product - Company" pages
            return "website page, not a release"
        if not ANNOUNCE.search(t):
            return "website page, not a release"
        if company.get("pr_needs_name") and name_position(t, company.get("aliases") or [company["name"]]) is None:
            return "repost about another company"
        return None
    if low_quality_source(source):
        return "low-quality source"
    aliases = company.get("aliases") or [company["name"]]
    pos = name_position(t, aliases)
    if pos is None:
        return "company not named"
    if pos > company.get("max_pos", 10):
        return "company only mentioned in passing"
    if company.get("must") and not any(re.search(r"(?<![A-Za-z])" + re.escape(m) + r"(?![A-Za-z])", t, re.I)
                                       for m in company["must"]):
        return "name match without context words"
    if ANALYST_VOICE.search(" ".join(t.split()[pos:pos + 8])):
        return "the firm is commenting, not the subject"
    for a in aliases:
        if re.search(r"(:|says|according to|\u2014|-)\s*" + re.escape(a) + r"\W*$", t, re.I):
            return "the firm is commenting, not the subject"
    if PASSING.search(" ".join(t.split()[max(0, pos - 2):pos])):
        return "company only mentioned in passing"
    if not BUSINESS.search(t):
        return "not about the business"
    return None


def topic_junk(title, source):
    """Lighter screen for industry and macro headlines (no company to anchor on)."""
    if SPAM.search(title):
        return "spam"
    if NOT_NEWS.search(title):
        return "not news"
    if low_quality_source(source):
        return "low-quality source"
    return None

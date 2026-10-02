"""Shared helpers: public RSS feeds, fetching/parsing (stdlib only), and source tiers.

Everything here uses free, public RSS. No API keys, no paid services. Feeds that
block automated access are simply skipped; we never try to get around a block."""
import json, re, urllib.request, urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent

FEEDS = {
    "ynet": "https://www.ynet.co.il/Integration/StoryRss1854.xml",
    "וואלה": "https://rss.walla.co.il/feed/22",
    "ישראל היום": "https://www.israelhayom.co.il/rss.xml",
    "מעריב": "https://www.maariv.co.il/Rss/RssFeedsMivzakiChadashot",
    "Times of Israel": "https://www.timesofisrael.com/feed/",
    "Jerusalem Post": "https://www.jpost.com/rss/rssfeedsheadlines.aspx",
    "BBC": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "Guardian": "https://www.theguardian.com/world/middleeast/rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "NYT": "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml",
}

UA = "Mozilla/5.0 (compatible; TamzitBot/1.0)"


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read() if e.code == 404 else b""
        if b"<rss" in body[:2000]:   # some servers (police.gov.il) send a valid feed with a 404 status
            return body
        raise


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    try:
        t = parsedate_to_datetime(s)
    except Exception:
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_feed(source, raw):
    """Yield {source, title, url, time, summary} from RSS or Atom bytes."""
    root = ET.fromstring(raw)
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        def get(name):
            for c in it:
                if c.tag.split("}")[-1] == name:
                    return c.text or ""
            return ""
        link = get("link") or next((c.get("href", "") for c in it if c.tag.split("}")[-1] == "link"), "")
        desc = re.sub(r"<[^>]+>", " ", get("description") or get("summary"))
        yield {
            "source": source,
            "title": re.sub(r"\s+", " ", get("title")).strip(),
            "url": link.strip(),
            "time": parse_time(get("pubDate") or get("pubdate") or get("published") or get("updated")),
            "summary": re.sub(r"\s+", " ", desc).strip()[:300],
        }


_SOURCES = None
def sources_config():
    global _SOURCES
    if _SOURCES is None:
        _SOURCES = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
    return _SOURCES


def domain(url):
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def outlet_name(url, fallback=""):
    """One name per news organisation, so ynet.co.il + ynetnews.com count as ONE independent source."""
    host, names = domain(url), sources_config()["names"]
    for d in sorted(names, key=len, reverse=True):
        if host == d or host.endswith("." + d):
            return names[d]
    return host or fallback


def tier_of(url):
    """1 official, 2 established outlet, 3 secondary/unknown. Longest matching suffix wins."""
    host, best, tier = domain(url), 0, 3
    for t, doms in sources_config()["tiers"].items():
        for d in doms:
            if (host == d or host.endswith("." + d)) and len(d) > best:
                best, tier = len(d), int(t)
    return tier


def article_type(url, title):
    """official / opinion / reporting. Opinion & analysis must never become facts."""
    cfg = sources_config()
    if tier_of(url) == 1:
        return "official"
    u, t = (url or "").lower(), (title or "").strip().lower()
    if any(p in u for p in cfg["opinion_url_patterns"]) or any(re.search(p, t) for p in cfg["opinion_title_patterns"]):
        return "opinion"
    return "reporting"

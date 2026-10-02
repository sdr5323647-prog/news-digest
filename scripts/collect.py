"""Collect public RSS headlines and cluster them into candidate EVENTS (no AI, stdlib only).

    python scripts/collect.py            # fetch feeds, merge into today's candidates file
    python scripts/collect.py --offline  # re-cluster the existing file without fetching

Output: data/candidates/YYYY-MM-DD.json
  articles: every headline seen today (deduplicated by URL), with tier + type
  clusters: groups of articles about the same event, biggest first

15 articles about one event become ONE cluster with sourceCount = number of distinct
outlets. The evening Claude run reads these clusters, verifies and writes the digest."""
import argparse, hashlib, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import FEEDS, ROOT, fetch, parse_feed, tier_of, article_type, outlet_name

try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:  # Windows without tzdata: close enough for picking the date
    IL = timezone(timedelta(hours=3))

KEEP = timedelta(hours=30)

STOP = set("""
של על את עם אל זה זו זאת הוא היא הם הן אני אנחנו לא כן גם רק כי אם או אבל כל עוד יותר פחות אחרי לפני בין תחת מול
היום אתמול מחר הבוקר הערב הלילה שנים שנה בשנה יום ימים שעה שעות כך כמו מה מי איך למה מתי שם פה עכשיו
the a an of to in on for and or but with at by from as is are was were be been has have had will would could should
after before over into about amid says said say new more than this that these those its it his her their they we you
נפצע נפצעה נפצעו נפגע נפגעה נפגעו פצוע פצועה פצועים באורח אורח בינוני קל קשה אנוש בן בת כבן כבת לאחר במהלך בעקבות
רחוב כביש בסמוך ליד סמוך אזור שבו שהיה שהיא שהוא ראשוני דיווח דיווחים חשד חשוד נעצר
""".split())
PREFIXES = "והבלמשכ"


def tokens(text):
    out = set()
    for w in re.findall(r"[\w֐-׿'\"]+", (text or "").lower()):
        w = w.strip("'\"")
        if len(w) < 2 or w in STOP:
            continue
        # light Hebrew prefix stripping: "והממשלה" -> "הממשלה" -> "ממשלה"
        for _ in range(2):
            if len(w) >= 5 and w[0] in PREFIXES and re.match(r"[֐-׿]", w):
                w = w[1:]
        if w not in STOP and len(w) >= 2:
            out.add(w)
    return out


def similar(a, b):
    """Same event if they share enough distinctive words (overlap coefficient)."""
    if not a or not b:
        return False
    inter = len(a & b)
    return inter >= 3 or (inter >= 2 and inter / min(len(a), len(b)) >= 0.5)


def cluster(articles):
    toks = [tokens(a["title"]) for a in articles]
    parent = list(range(len(articles)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            if similar(toks[i], toks[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, a in enumerate(articles):
        groups.setdefault(find(i), []).append(a)
    out = []
    for members in groups.values():
        members.sort(key=lambda a: a["time"])
        outlets = sorted({a["outlet"] for a in members})
        types = [a["type"] for a in members]
        out.append({
            "id": hashlib.sha1(members[0]["url"].encode()).hexdigest()[:10],
            "title": max(members, key=lambda a: (a["tier"] == 1, len(tokens(a["title"]))))["title"],
            "sourceCount": len(outlets),
            "outlets": outlets,
            "bestTier": min(a["tier"] for a in members),
            "hasOfficial": "official" in types,
            "reportingCount": sum(t != "opinion" for t in types),
            "opinionOnly": all(t == "opinion" for t in types),
            "firstSeen": members[0]["time"],
            "lastSeen": members[-1]["time"],
            "articles": [{k: a[k] for k in ("source", "title", "url", "tier", "type", "time")} for a in members[:10]],
        })
    out.sort(key=lambda c: (c["sourceCount"], c["reportingCount"]), reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    day = now.astimezone(IL).strftime("%Y-%m-%d")
    path = ROOT / "data" / "candidates" / f"{day}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"date": day, "articles": []}
    by_url = {a["url"]: a for a in data["articles"]}

    if not args.offline:
        for source, url in FEEDS.items():
            try:
                for it in parse_feed(source, fetch(url)):
                    if not it["time"] or not it["url"] or now - it["time"] > KEEP or it["url"] in by_url:
                        continue
                    by_url[it["url"]] = {
                        "source": source, "outlet": outlet_name(it["url"], source),
                        "title": it["title"], "url": it["url"], "summary": it["summary"],
                        "time": it["time"].isoformat(), "tier": tier_of(it["url"]), "type": article_type(it["url"], it["title"]),
                    }
            except Exception as e:
                print(f"feed skipped: {source}: {e}", file=sys.stderr)

    cutoff = (now - KEEP).isoformat()
    articles = sorted((a for a in by_url.values() if a["time"] >= cutoff), key=lambda a: a["time"])
    clusters = cluster(articles)
    data.update({"updated": now.isoformat(), "articles": articles, "clusters": clusters,
                 "stats": {"articles": len(articles), "clusters": len(clusters),
                           "multiSource": sum(c["sourceCount"] >= 2 for c in clusters)}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # keep only the last 7 days of candidates
    for old in sorted((ROOT / "data" / "candidates").glob("*.json"))[:-7]:
        old.unlink()
    print(f"{day}: {len(articles)} articles -> {len(clusters)} event clusters "
          f"({data['stats']['multiSource']} reported by 2+ outlets)")


if __name__ == "__main__":
    main()

"""Validate digest files before they are published. Exit code 1 = do not publish.

    python scripts/validate.py                 # all files in data/daily and data/weekly
    python scripts/validate.py data/daily/2026-10-03.json

Enforces the editorial rules that matter most:
  * a claim is never presented as a fact (status + attribution wording)
  * VERIFIED/REPORTED need real sources; opinion pieces alone never count
  * one event = one item (no duplicate ids / near-duplicate titles)
  * an event already shown in an earlier digest must say what changed
  * an empty day is allowed, a made-up one is not: no events => a note explaining why"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import ROOT
from collect import tokens
from registry import load_daily, build

CATEGORIES = {"security", "politics", "economy", "society", "law", "tech", "israel_world", "world", "judaism", "culture", "sport"}
KINDS = {"decision", "event", "statement", "past", "dispute", "data", "legal", "negotiation"}
NOISE = {"gossip", "celebrity", "entertainment", "viral", "personal", "clickbait", "local"}
MAIN_STATUS = {"VERIFIED", "REPORTED"}
SIDE_STATUS = {"REPORTED", "CLAIM", "UNCONFIRMED", "CONFLICTING"}
SOURCE_TYPES = {"reporting", "official", "analysis", "opinion"}
ATTRIBUTION = re.compile(r"על פי|לפי|לטענת|טוענ|טען|טענה|טענו|דיווח|דווח|מדווח|נמסר|מסר|לדברי|הודיע|אמר|according|claim|report|said|alleg", re.I)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def independent(sources, types=("reporting", "official"), max_tier=2):
    return {s["name"] for s in sources if s.get("type") in types and s.get("tier", 3) <= max_tier}


def check_event(e, section, date, errs):
    where = f"{section}:{e.get('id', '?')}"
    for f in ("id", "title", "summary", "why", "status", "importance", "categories", "kind", "entities", "sources", "sourceCount", "firstSeen", "lastUpdated", "change"):
        if f not in e:
            errs.append(f"{where}: missing field '{f}'")
    if errs and any(x.startswith(where + ": missing") for x in errs):
        return
    if not SLUG.match(e["id"]):
        errs.append(f"{where}: id must be a stable lowercase slug (no date), e.g. 'flydubai-attack'")
    if not (isinstance(e["importance"], int) and 1 <= e["importance"] <= 5):
        errs.append(f"{where}: importance must be an integer 1-5")
    if not e["categories"] or not set(e["categories"]) <= CATEGORIES:
        errs.append(f"{where}: categories must be a non-empty subset of {sorted(CATEGORIES)}")
    if e["kind"] not in KINDS:
        errs.append(f"{where}: kind must be one of {sorted(KINDS)}")
    if not set(e.get("noise", [])) <= NOISE:
        errs.append(f"{where}: noise must be a subset of {sorted(NOISE)}")
    for d in ("firstSeen", "lastUpdated"):
        if not DATE.match(str(e[d])):
            errs.append(f"{where}: {d} must be YYYY-MM-DD")
    if e["firstSeen"] > e["lastUpdated"] or e["lastUpdated"] > date:
        errs.append(f"{where}: dates out of order (firstSeen <= lastUpdated <= digest date)")
    src = e["sources"]
    if not src:
        errs.append(f"{where}: needs at least one source")
    for s in src:
        if not str(s.get("url", "")).startswith("http") or not s.get("name"):
            errs.append(f"{where}: every source needs name + http(s) url")
        if s.get("type") not in SOURCE_TYPES or s.get("tier") not in (1, 2, 3):
            errs.append(f"{where}: source '{s.get('name')}' needs tier 1-3 and type in {sorted(SOURCE_TYPES)}")
    if src and not any(s.get("type") in ("reporting", "official") for s in src):
        errs.append(f"{where}: opinion/analysis alone is not news - needs a reporting or official source")
    if e["sourceCount"] < len({s["name"] for s in src if s.get("type") in ("reporting", "official")}):
        errs.append(f"{where}: sourceCount is smaller than the number of listed reporting sources")

    st = e["status"]
    if section == "events":
        if st not in MAIN_STATUS:
            errs.append(f"{where}: status {st} cannot appear in main news - move it to 'unverified'")
        if st == "VERIFIED" and len(independent(src)) < 2 and not any(s.get("tier") == 1 or s.get("type") == "official" for s in src):
            errs.append(f"{where}: VERIFIED needs 2+ independent tier-1/2 reporting sources or an official source")
        if st == "REPORTED" and not independent(src):
            errs.append(f"{where}: REPORTED needs at least one tier-1/2 reporting source")
    else:
        if st not in SIDE_STATUS:
            errs.append(f"{where}: unverified items must have status CLAIM/UNCONFIRMED/CONFLICTING/REPORTED")
        if not ATTRIBUTION.search(e["summary"]) or not ATTRIBUTION.search(e["title"] + " " + e["summary"][:120]):
            errs.append(f"{where}: unverified text must attribute the claim explicitly ('על פי דיווח של X', 'גורם Y טען כי')")


def check_file(path, errs):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    date, typ = d.get("date", ""), d.get("type")
    if d.get("schema") != 2:
        errs.append("schema must be 2"); return
    if not DATE.match(date) or typ not in ("daily", "weekly"):
        errs.append("date/type invalid"); return
    events, unv = d.get("events", []), d.get("unverified", [])
    limit = 10 if typ == "daily" else 12
    if len(events) > limit:
        errs.append(f"too many events ({len(events)} > {limit}): this is a digest, not a feed")
    if not events and not d.get("note"):
        errs.append("no events: add a 'note' (e.g. 'לא נמצאו היום אירועים שעברו את סף האימות') instead of inventing news")
    for e in events:
        check_event(e, "events", date, errs)
    for e in unv:
        check_event(e, "unverified", date, errs)

    allv = events + unv
    ids = [e.get("id") for e in allv]
    for i in {x for x in ids if ids.count(x) > 1}:
        errs.append(f"duplicate event id '{i}': one event = one item")
    toks = [(e.get("id"), tokens(e.get("title", ""))) for e in allv]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            a, b = toks[i][1], toks[j][1]
            inter = len(a & b)
            if inter >= 3 and inter / max(1, min(len(a), len(b))) >= 0.6:
                errs.append(f"'{toks[i][0]}' and '{toks[j][0]}' look like the same event - merge them")

    if typ == "daily":
        prior = build(load_daily(before=date))
        for e in allv:
            r = prior.get(e.get("id"))
            if not r:
                continue
            if len(str(e.get("change", "")).strip()) < 10:
                errs.append(f"'{e['id']}' already appeared on {r['lastDigest']}: write what changed since then in 'change', or drop it")
            if e.get("lastUpdated") != date:
                errs.append(f"'{e['id']}' is a repeat: lastUpdated must be today ({date}) because something changed today")
            if e.get("firstSeen") != r["firstSeen"]:
                errs.append(f"'{e['id']}': firstSeen must stay {r['firstSeen']} (from the registry)")


def main(paths):
    if not paths:
        paths = sorted(str(p) for p in (ROOT / "data").glob("daily/*.json")) + sorted(str(p) for p in (ROOT / "data").glob("weekly/*.json"))
    bad = 0
    for p in paths:
        errs = []
        try:
            check_file(p, errs)
        except Exception as ex:
            errs.append(f"cannot read: {ex}")
        name = Path(p).as_posix().split("data/")[-1]
        if errs:
            bad += 1
            print(f"FAIL {name}")
            for x in errs:
                print("   -", x)
        else:
            print(f"ok   {name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

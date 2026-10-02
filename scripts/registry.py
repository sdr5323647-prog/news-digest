"""Event registry: every event that ever appeared in a daily digest, keyed by its stable id.

    python scripts/registry.py    # rebuild data/events.json from data/daily/*.json

Rebuilt from scratch each time, so it can never drift from the published digests.
The evening run reads it to know what readers were already told ("what changed?")."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import ROOT


def load_daily(before=None):
    """All daily digests (optionally only those dated before `before`), oldest first."""
    out = []
    for p in sorted((ROOT / "data" / "daily").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if before and d.get("date", p.stem) >= before:
            continue
        out.append(d)
    return out


def build(digests):
    reg = {}
    for d in digests:
        for section in ("events", "unverified"):
            for e in d.get(section, []):
                r = reg.setdefault(e["id"], {"firstSeen": e.get("firstSeen", d["date"]), "dates": []})
                r["firstSeen"] = min(r["firstSeen"], e.get("firstSeen", d["date"]))
                r["dates"].append(d["date"])
                r.update({"title": e["title"], "summary": e["summary"], "status": e.get("status"),
                          "lastUpdated": e.get("lastUpdated", d["date"]), "lastDigest": d["date"], "section": section})
    return reg


def main():
    reg = build(load_daily())
    (ROOT / "data" / "events.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"registry: {len(reg)} events")


if __name__ == "__main__":
    main()

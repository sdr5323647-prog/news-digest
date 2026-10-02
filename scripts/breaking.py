"""Breaking-news watcher for Tamzit. No AI: reads RSS headlines and raises an alert
only when several independent outlets report the same rare, severe kind of event.

Writes data/breaking.json only when the alert state changes, so the repo isn't
flooded with commits."""
import json, re, sys, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import FEEDS, fetch, parse_feed

# Rare, severe event types. Each needs MIN_SOURCES different outlets inside WINDOW.
GROUPS = {
    "war": ("הכרזת מלחמה", [
        r"הכריז(ה|ו)? (על )?מלחמה", r"הכרזת מלחמה", r"declares? war", r"declaration of war",
    ]),
    "attack": ("מתקפה רחבה על ישראל", [
        r"(מתקפת|מטח|מטחי|שיגור) (טילים|רקטות) (נרחב|כבד|מאסיבי)", r"מתקפה (נרחבת|מאסיבית) על ישראל",
        r"(massive|large-scale|unprecedented) (missile |rocket |drone )?(attack|barrage|strike)s? (on|against|at) israel",
    ]),
    "casualties": ("אירוע רב נפגעים", [
        r"רב[- ]נפגעים", r"עשרות הרוגים", r"mass[- ]casualty", r"dozens (of people )?(killed|dead)",
    ]),
    "assassination": ("התנקשות / חיסול בכיר", [
        r"נרצח", r"התנקשות", r"assassinat",
    ]),
    "ceasefire": ("הסכם / הפסקת אש", [
        r"(נחתם|הושג|נכנס(ה)? לתוקף).{0,20}(הסכם|הפסקת אש)", r"(הסכם|הפסקת אש).{0,20}(נחתם|הושג|נכנס(ה)? לתוקף)",
        r"ceasefire (agreed|reached|takes effect|announced|signed)", r"(peace|ceasefire) (deal|agreement) (signed|reached|agreed)",
    ]),
    "earthquake": ("רעידת אדמה", [
        r"רעידת אדמה (חזקה|עוצמתית)", r"(strong|powerful|major) earthquake",
    ]),
    "leadership": ("שינוי דרמטי בהנהגה", [
        r"ראש הממשלה (התפטר|הודיע על התפטרותו|מת|נפטר)", r"prime minister (resigns|has died|dies)",
    ]),
}

WINDOW = timedelta(minutes=75)   # GitHub's scheduler can lag; look back generously
MIN_SOURCES = 3
ALERT_TTL = timedelta(hours=8)
OUT = Path("data/breaking.json")


def main():
    now = datetime.now(timezone.utc)
    recent = []
    for source, url in FEEDS.items():
        try:
            recent += [i for i in parse_feed(source, fetch(url)) if i["time"] and now - i["time"] <= WINDOW and i["title"]]
        except Exception as e:
            print(f"feed failed: {source}: {e}", file=sys.stderr)

    hits = {}
    for g, (_, patterns) in GROUPS.items():
        rx = re.compile("|".join(patterns), re.IGNORECASE)
        matched = [i for i in recent if rx.search(i["title"])]
        if len({i["source"] for i in matched}) >= MIN_SOURCES:
            hits[g] = matched

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"active": False}
    old_alert = old.get("alert") if old.get("active") else None
    if old_alert and datetime.fromisoformat(old_alert["expires_at"]) <= now:
        old_alert = None

    if hits:
        g, matched = max(hits.items(), key=lambda kv: len({i["source"] for i in kv[1]}))
        matched.sort(key=lambda i: i["time"], reverse=True)
        seen, top = set(), []
        for i in matched:  # one headline per source first, then the rest
            if i["source"] not in seen:
                seen.add(i["source"]); top.append(i)
        top += [i for i in matched if i not in top]
        new_items = [{"source": i["source"], "title": i["title"], "url": i["url"], "time": i["time"].isoformat()} for i in top[:6]]
        if old_alert and old_alert["group"] == g:
            alert = {**old_alert, "items": new_items, "expires_at": (now + ALERT_TTL).isoformat()}
        else:
            alert = {
                "id": hashlib.sha1(f"{g}{now.isoformat()}".encode()).hexdigest()[:10],
                "group": g, "label": GROUPS[g][0],
                "detected_at": now.isoformat(), "expires_at": (now + ALERT_TTL).isoformat(),
                "items": new_items,
            }
        state = {"active": True, "alert": alert}
    else:
        state = {"active": True, "alert": old_alert} if old_alert else {"active": False}

    # Only rewrite when something meaningful changed (expires_at bumps count at most once an hour).
    def key(s):
        a = s.get("alert") or {}
        return (s.get("active"), a.get("id"), a.get("expires_at", "")[:13], tuple(i["url"] for i in a.get("items", [])))
    if key(state) != key(old) or not OUT.exists():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("breaking.json updated:", state.get("active"), (state.get("alert") or {}).get("label"))
    else:
        print("no change; recent headlines checked:", len(recent))


if __name__ == "__main__":
    main()

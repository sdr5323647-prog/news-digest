"""Run: python -m unittest discover -s tests   (stdlib only, no network)"""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import collect, validate, registry, feeds, weather


def art(source, title, url, t="2026-10-03T10:00:00+00:00", tier=2, typ="reporting"):
    return {"source": source, "outlet": source, "title": title, "url": url, "time": t, "tier": tier, "type": typ}


def src(name, tier=2, typ="reporting"):
    return {"name": name, "url": f"https://{name}.example/x", "tier": tier, "type": typ}


def ev(id, **o):
    e = {"id": id, "title": "כותרת " + id, "summary": "סיכום " + id, "why": "למה", "change": "", "status": "VERIFIED",
         "importance": 3, "categories": ["politics"], "kind": "decision", "entities": [], "noise": [],
         "sources": [src("a"), src("b")], "sourceCount": 2, "firstSeen": "2026-10-03", "lastUpdated": "2026-10-03"}
    e.update(o)
    return e


def check(digest, prior_days=()):
    """Validate a digest dict, with optional earlier daily digests in a temp data dir."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data" / "daily").mkdir(parents=True)
        for d in prior_days:
            (root / "data" / "daily" / f"{d['date']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        p = root / "data" / "daily" / f"{digest['date']}.json"
        p.write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
        old = registry.ROOT
        registry.ROOT = root
        try:
            errs = []
            validate.check_file(p, errs)
            return errs
        finally:
            registry.ROOT = old


def daily(date, events, unverified=(), **o):
    d = {"schema": 2, "date": date, "type": "daily", "headline": "", "events": list(events), "unverified": list(unverified), "note": ""}
    d.update(o)
    return d


class Clustering(unittest.TestCase):
    def test_same_event_from_5_outlets_is_one_cluster(self):
        arts = [
            art("ynet", "טייס משנה דקר את הקברניט בטיסת פליידובאי לתל אביב", "https://ynet.co.il/1"),
            art("וואלה", "בטיסת פליידובאי: טייס המשנה דקר את הקברניט", "https://walla.co.il/2"),
            art("ישראל היום", "הקברניט נדקר בידי טייס המשנה בטיסת פליידובאי", "https://israelhayom.co.il/3"),
            art("מעריב", "דרמה בטיסת פליידובאי: טייס משנה דקר קברניט", "https://maariv.co.il/4"),
            art("כאן", "טיסת פליידובאי לתל אביב: הקברניט נדקר", "https://kan.org.il/5"),
            art("ynet", "בנק ישראל הותיר את הריבית ללא שינוי", "https://ynet.co.il/6"),
        ]
        cl = collect.cluster(arts)
        self.assertEqual(len(cl), 2)
        self.assertEqual(cl[0]["sourceCount"], 5)
        self.assertEqual(len(cl[0]["articles"]), 5)

    def test_generic_injury_wording_does_not_merge_unrelated_events(self):
        arts = [art("מעריב", "רוכב אופנוע בן 18 נפצע באורח בינוני ברחוב שבטי ישראל", "https://m/1"),
                art("מעריב", "פועל בן 25 נפצע באורח בינוני לאחר שנפל מגובה", "https://m/2")]
        self.assertEqual(len(collect.cluster(arts)), 2)

    def test_opinion_and_official_are_classified(self):
        self.assertEqual(feeds.article_type("https://www.jpost.com/opinion/article-1", "x"), "opinion")
        self.assertEqual(feeds.article_type("https://www.ynet.co.il/news/1", "פרשנות: מה זה אומר"), "opinion")
        self.assertEqual(feeds.article_type("https://www.idf.il/news/1", "x"), "official")
        self.assertEqual(feeds.article_type("https://www.ynet.co.il/news/1", "צה\"ל תקף"), "reporting")
        self.assertEqual(feeds.tier_of("https://www.gov.il/he/x"), 1)
        self.assertEqual(feeds.tier_of("https://x.com/someone"), 3)
        self.assertEqual(feeds.outlet_name("https://www.ynetnews.com/a"), feeds.outlet_name("https://www.ynet.co.il/b"))


class Validation(unittest.TestCase):
    def test_valid_digest_passes(self):
        self.assertEqual(check(daily("2026-10-03", [ev("budget-vote")])), [])

    def test_claim_cannot_be_main_news(self):
        errs = check(daily("2026-10-03", [ev("hamas-claim", status="CLAIM")]))
        self.assertTrue(any("cannot appear in main news" in e for e in errs), errs)

    def test_unverified_text_must_attribute_the_claim(self):
        bad = ev("rumor", status="UNCONFIRMED", title="איראן תקפה", summary="איראן תקפה מתקן בעיראק.")
        good = ev("rumor2", status="UNCONFIRMED", title="על פי דיווח ברויטרס: תקיפה בעיראק", summary="על פי דיווח של רויטרס, מתקן הותקף.")
        errs = check(daily("2026-10-03", [ev("x")], unverified=[bad, good]))
        self.assertTrue(any("rumor:" in e and "attribute" in e for e in errs), errs)
        self.assertFalse(any("rumor2" in e for e in errs), errs)

    def test_verified_needs_two_independent_sources_or_official(self):
        one = ev("one-source", sources=[src("a")], sourceCount=1)
        official = ev("official", sources=[src("idf", 1, "official")], sourceCount=1)
        errs = check(daily("2026-10-03", [one, official]))
        self.assertTrue(any("one-source" in e and "VERIFIED needs" in e for e in errs), errs)
        self.assertFalse(any("official:" in e for e in errs), errs)

    def test_opinion_alone_is_not_news(self):
        errs = check(daily("2026-10-03", [ev("op-ed", status="REPORTED", sources=[src("a", 2, "opinion")], sourceCount=1)]))
        self.assertTrue(any("opinion/analysis alone" in e for e in errs), errs)

    def test_duplicate_event_is_rejected(self):
        a = ev("flydubai-attack", title="טייס משנה דקר את הקברניט בטיסת פליידובאי")
        b = ev("flydubai-stabbing", title="בטיסת פליידובאי טייס משנה דקר את הקברניט")
        errs = check(daily("2026-10-03", [a, b]))
        self.assertTrue(any("same event" in e for e in errs), errs)

    def test_repeat_without_change_is_rejected_and_with_change_passes(self):
        day1 = daily("2026-10-02", [ev("us-iran-talks", firstSeen="2026-10-02", lastUpdated="2026-10-02")])
        same = daily("2026-10-03", [ev("us-iran-talks", firstSeen="2026-10-02", lastUpdated="2026-10-03")])
        errs = check(same, [day1])
        self.assertTrue(any("write what changed" in e for e in errs), errs)
        upd = daily("2026-10-03", [ev("us-iran-talks", firstSeen="2026-10-02", lastUpdated="2026-10-03",
                                      change="משלחת איראן עזבה את ניו יורק והמגעים נתקעו.")])
        self.assertEqual(check(upd, [day1]), [])

    def test_empty_day_needs_an_honest_note_not_invented_news(self):
        self.assertTrue(check(daily("2026-10-03", [])))
        self.assertEqual(check(daily("2026-10-03", [], note="לא נמצאו היום אירועים שעברו את סף האימות.")), [])

    def test_no_infinite_feed(self):
        many = [ev(f"event-{i}", title=f"נושא {i} מספר {i * 7} ייחודי {i * 13}") for i in range(14)]
        self.assertTrue(any("too many events" in e for e in check(daily("2026-10-03", many))))


class Weather(unittest.TestCase):
    CITIES = """<?xml version="1.0" encoding="utf-8"?><IsraelCitiesWeatherForecastMorning><Location><LocationMetaData>
      <LocationId>510</LocationId><LocationNameEng>Jerusalem</LocationNameEng><LocationNameHeb>ירושלים</LocationNameHeb></LocationMetaData>
      <LocationData><TimeUnitData><Date>2099-01-10</Date>
        <Element><ElementName>Maximum temperature</ElementName><ElementValue>6</ElementValue></Element>
        <Element><ElementName>Minimum temperature</ElementName><ElementValue>1</ElementValue></Element>
        <Element><ElementName>Weather code</ElementName><ElementValue>1060</ElementValue></Element>
      </TimeUnitData></LocationData></Location></IsraelCitiesWeatherForecastMorning>""".encode()
    SIXHR = """<?xml version="1.0" encoding="utf-8"?><LocationForecasts><Location><LocationMetaData><LocationId>717</LocationId>
      <LocationNameEng>Mount Hermon</LocationNameEng></LocationMetaData><LocationData>
      <Forecast><ForecastTime>2099-01-10 03:00:00</ForecastTime><Temperature>-3.2</Temperature><WeatherCode>1230</WeatherCode></Forecast>
      <Forecast><ForecastTime>2099-01-10 09:00:00</ForecastTime><Temperature>-1</Temperature><WeatherCode>1520</WeatherCode></Forecast>
      </LocationData></Location></LocationForecasts>""".encode()
    ALERTS = b"""<?xml version='1.0' encoding='us-ascii'?><rss version="2.0"><channel><item><title>&#1513;&#1500;&#1490;</title>
      <description>&lt;p&gt;&#1488;&#1494;&#1492;&#1512;&#1492; &#1499;&#1514;&#1493;&#1502;&#1492;&lt;/p&gt;</description><pubDate>x</pubDate></item></channel></rss>"""

    def test_parse_forecast_snow_and_alerts(self):
        d = weather.build(self.CITIES, self.SIXHR, self.ALERTS)
        names = [c["name"] for c in d["cities"]]
        self.assertEqual(names, ["החרמון", "ירושלים"])
        jer = d["cities"][1]["days"][0]
        self.assertEqual((jer["min"], jer["max"], jer["desc"]), (1, 6, "שלג"))
        hermon = d["cities"][0]["days"][0]
        self.assertEqual((hermon["min"], hermon["max"], hermon["desc"]), (-3, -1, "שלג כבד"), "worst 6-hour code wins")
        self.assertEqual(d["snow"], [{"place": "החרמון", "dates": ["2099-01-10"]}])
        self.assertEqual(d["alerts"][0]["title"], "שלג")
        self.assertEqual(d["alerts"][0]["text"], "אזהרה כתומה")

    def test_missing_files_do_not_crash(self):
        d = weather.build(self.CITIES, None, None)
        self.assertEqual(d["snow"], [])
        self.assertEqual(d["alerts"], [])


class PublishedData(unittest.TestCase):
    def test_every_published_digest_is_valid(self):
        self.assertEqual(validate.main([]), 0)


class NoPaidDependencies(unittest.TestCase):
    def test_no_paid_apis_or_keys_anywhere(self):
        root = Path(__file__).resolve().parent.parent
        banned = ["openai", "api.anthropic.com", "generativelanguage", "newsapi", "firebase", "supabase", "vercel",
                  "netlify", "sendgrid", "mailgun", "twilio", "api_key", "apikey", "secrets."]
        for p in root.rglob("*"):
            # code & config only (docs may name the banned services; data/ holds news text)
            if p.is_file() and p.suffix in {".py", ".js", ".html", ".yml", ".json", ".webmanifest"} \
                    and ".git" not in p.parts and "data" not in p.parts and p.name != "test_pipeline.py":
                text = p.read_text(encoding="utf-8", errors="ignore").lower()
                for b in banned:
                    self.assertNotIn(b, text, f"{p.relative_to(root)} mentions '{b}'")

    def test_python_uses_stdlib_only(self):
        root = Path(__file__).resolve().parent.parent / "scripts"
        allowed = {"argparse", "hashlib", "json", "re", "sys", "urllib", "datetime", "email", "pathlib", "xml", "zoneinfo",
                   "feeds", "collect", "registry", "validate", "weather", "tempfile", "unittest", "html"}
        import re as _re
        for p in root.glob("*.py"):
            for m in _re.finditer(r"^(?:from|import)\s+([\w.]+)", p.read_text(encoding="utf-8"), _re.M):
                self.assertIn(m.group(1).split(".")[0], allowed, f"{p.name} imports {m.group(1)}")


if __name__ == "__main__":
    unittest.main()

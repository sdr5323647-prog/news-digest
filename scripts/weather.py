"""Weather from the Israel Meteorological Service (IMS) - official, public, free, no key.

    python scripts/weather.py      # -> data/weather.json (rewritten only when the forecast changes)

Sources (public XML/RSS published by IMS for anyone to use):
  isr_cities.xml                       4-day forecast for 15 cities (Hebrew names)
  isr_cities_1week_6hr_forecast.xml    6-hourly forecast for 175 locations (incl. Mount Hermon) -> snow detection
  rssAlert_general_country_he.xml      official warnings (storms, floods, snow, heat...)"""
import html, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import ROOT, fetch
from collect import IL

BASE = "https://ims.gov.il/sites/default/files/ims_data/"
CITIES_URL = BASE + "xml_files/isr_cities.xml"
SIXHR_URL = BASE + "xml_files/isr_cities_1week_6hr_forecast.xml"
ALERTS_URL = BASE + "rss/alert/rssAlert_general_country_he.xml"
OUT = ROOT / "data" / "weather.json"

# IMS weather codes -> Hebrew + icon. Unknown codes just show the temperatures.
CODES = {
    "1250": ("בהיר", "☀️"), "1220": ("מעונן חלקית", "⛅"), "1230": ("מעונן", "☁️"),
    "1530": ("מעונן חלקית, ייתכן גשם", "🌦️"), "1540": ("מעונן, ייתכן גשם", "🌦️"), "1560": ("מעונן, גשם קל", "🌧️"),
    "1140": ("גשום", "🌧️"), "1020": ("סופות רעמים", "⛈️"), "1510": ("סוער", "🌬️"), "1260": ("רוחות חזקות", "🌬️"),
    "1060": ("שלג", "❄️"), "1070": ("שלג קל", "🌨️"), "1080": ("שלג מעורב בגשם", "🌨️"), "1520": ("שלג כבד", "❄️"),
    "1160": ("ערפל", "🌫️"), "1570": ("אובך", "🌫️"), "1010": ("סופות חול", "🌪️"),
    "1310": ("חם", "🌡️"), "1580": ("חם מאוד", "🔥"), "1270": ("הביל", "💧"),
    "1320": ("קר", "🥶"), "1590": ("קר מאוד", "🥶"), "1300": ("כפור", "🧊"),
}
SNOW = {"1060", "1070", "1080", "1520"}
# order used to pick the "headline" weather of a day from several 6-hour slots (most significant wins)
SEVERITY = ["1520", "1060", "1080", "1070", "1020", "1140", "1510", "1560", "1540", "1530", "1010", "1260",
            "1590", "1580", "1300", "1160", "1570", "1320", "1310", "1270", "1230", "1220", "1250"]
EXTRA = {"717": "החרמון"}   # locations taken from the 6-hour file (not in the 15-city file)
HEB = {"Mount Hermon": "החרמון", "Zefat": "צפת", "Jerusalem": "ירושלים", "Qazrin": "קצרין", "Mizpe Ramon": "מצפה רמון",
       "Tel Hebron": "חברון", "Qiryat Arba": "קריית ארבע", "Rosh Zorim": "גוש עציון", "Nebi Samuel": "נבי סמואל",
       "Mount Gerizim": "הר גריזים", "Ariel": "אריאל", "Ma'ale Adummim": "מעלה אדומים", "Haifa": "חיפה", "Nazareth": "נצרת"}


def label(code):
    d, i = CODES.get(code, ("", ""))
    return {"code": code, "desc": d, "icon": i}


def parse_cities(raw):
    root = ET.fromstring(raw)
    out = []
    for loc in root.iter("Location"):
        meta = loc.find("LocationMetaData")
        days = []
        for t in loc.iter("TimeUnitData"):
            el = {e.findtext("ElementName"): e.findtext("ElementValue") for e in t.iter("Element")}
            if el.get("Maximum temperature") is None:
                continue
            days.append(dict(date=t.findtext("Date"), min=_num(el.get("Minimum temperature")),
                             max=_num(el.get("Maximum temperature")), **label(el.get("Weather code", ""))))
        out.append({"id": meta.findtext("LocationId"), "name": meta.findtext("LocationNameHeb") or meta.findtext("LocationNameEng"), "days": days})
    return out


def parse_6hr(raw):
    """Daily summaries for EXTRA locations + every (location, date) where snow is forecast."""
    root = ET.fromstring(raw)
    extra, snow = [], []
    for loc in root.iter("Location"):
        lid = loc.findtext(".//LocationId")
        name = loc.findtext(".//LocationNameEng") or ""
        by_day = {}
        for f in loc.iter("Forecast"):
            day = (f.findtext("ForecastTime") or "")[:10]
            by_day.setdefault(day, []).append(f)
        snow_days = [d for d, fs in sorted(by_day.items()) if any(f.findtext("WeatherCode") in SNOW for f in fs)]
        if snow_days:
            snow.append({"place": HEB.get(name, name), "dates": snow_days[:4]})
        if lid in EXTRA:
            days = []
            for d, fs in sorted(by_day.items()):
                temps = [_num(f.findtext("Temperature")) for f in fs if f.findtext("Temperature")]
                codes = [f.findtext("WeatherCode") for f in fs]
                code = min(codes, key=lambda c: SEVERITY.index(c) if c in SEVERITY else 99)
                days.append(dict(date=d, min=round(min(temps)), max=round(max(temps)), **label(code)))
            extra.append({"id": lid, "name": EXTRA[lid], "days": days})
    return extra, snow


def parse_alerts(raw):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        text = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        out.append({"title": html.unescape(it.findtext("title") or "").strip(),
                    "text": re.sub(r"\s+", " ", text).strip(), "time": it.findtext("pubDate") or "",
                    "url": "https://www.ims.gov.il/he/IMSWarnings"})
    return out


def _num(v):
    try:
        return round(float(v))
    except (TypeError, ValueError):
        return None


def build(cities_raw, sixhr_raw, alerts_raw):
    today = datetime.now(timezone.utc).astimezone(IL).strftime("%Y-%m-%d")   # Israel date, not UTC
    cities = parse_cities(cities_raw) if cities_raw else []
    extra, snow = parse_6hr(sixhr_raw) if sixhr_raw else ([], [])
    for c in cities + extra:   # drop days that already passed
        c["days"] = [d for d in c["days"] if d["date"] >= today][:4]
    snow = [s for s in ({"place": s["place"], "dates": [d for d in s["dates"] if d >= today]} for s in snow) if s["dates"]]
    return {"source": "השירות המטאורולוגי הישראלי", "sourceUrl": "https://ims.gov.il",
            "cities": [c for c in extra + cities if c["days"]], "snow": snow[:12],
            "alerts": parse_alerts(alerts_raw) if alerts_raw else []}


def main():
    raws = {}
    for key, url in (("cities", CITIES_URL), ("sixhr", SIXHR_URL), ("alerts", ALERTS_URL)):
        try:
            raws[key] = fetch(url, timeout=40)
        except Exception as e:
            print(f"IMS {key} unavailable: {e}", file=sys.stderr)
    if "cities" not in raws:
        print("no forecast fetched; keeping the previous file")
        return
    data = build(raws.get("cities"), raws.get("sixhr"), raws.get("alerts"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "updated"} == data:
        print("weather unchanged")
        return
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"weather.json updated: {len(data['cities'])} places, {len(data['alerts'])} warnings, snow in {len(data['snow'])} places")


if __name__ == "__main__":
    main()

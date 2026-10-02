# תמצית

**מה באמת חשוב לדעת השבוע, בלי לבזבז זמן על זבל חדשותי.**
חינם לתמיד, בלי פרסומות, בלי paywall, בלי API בתשלום.

האתר: https://sdr5323647-prog.github.io/news-digest/

## איך זה עובד

```
כל 3 שעות (GitHub Actions, בלי AI)   scripts/collect.py
  RSS ציבורי ← סיווג (דיווח/דעה/רשמי, Tier 1-3) ← קיבוץ כתבות לאירועים
  → data/candidates/YYYY-MM-DD.json

כל ערב (Claude, במסגרת מנוי Pro קיים)  DIGEST_PROMPT.md
  אימות (VERIFIED / REPORTED / CLAIM / CONFLICTING / UNCONFIRMED)
  ← איחוד ← חשיבות ציבורית ← "מה השתנה" מול data/events.json
  → data/daily/YYYY-MM-DD.json  ← scripts/validate.py חייב לעבור

בטלפון של כל קורא (js/engine.js, בלי שרת)
  רלוונטיות אישית מ-👍/👎 + סיבות + "🧠 למד את המערכת"
  → המרכזי · חשוב לדעת · ⚠️ טרם אומתו · כבר ראית · פחות רלוונטי לך

כל 15 דקות (GitHub Actions, בלי AI)   scripts/breaking.py → באנר מבזק
```

| קובץ | תפקיד |
|---|---|
| `index.html`, `js/engine.js` | האתר. כל ההחלטות מה להציג נמצאות ב-engine (פונקציות טהורות, עם בדיקות) |
| `DIGEST_PROMPT.md` | ההוראות לריצת Claude שכותבת את התקציר |
| `rules.md` | כללי עריכה ואמינות; מתעדכן ממשוב העורך |
| `data/sources.json` | היררכיית מקורות (Tier 1/2/3) וזיהוי דעה/פרשנות |
| `scripts/collect.py` | איסוף RSS וקיבוץ לאירועים |
| `scripts/validate.py` | שומר הסף: טענה לא מוצגת כעובדה, אין כפילויות, אין חזרה בלי שינוי |
| `scripts/registry.py` | `data/events.json`: כל אירוע שפורסם, למעקב "מה השתנה" |
| `scripts/breaking.py` | זיהוי מבזקים מכותרות בלבד |
| `tests/` | בדיקות (Node + Python, ספריות סטנדרטיות בלבד) |

## איך מריצים

דרישות: Python 3.10+ ו-Node 18+ (חינמיים). אין `pip install` ואין `npm install`.

```bash
python scripts/collect.py                         # איסוף מועמדים להיום
python scripts/validate.py                        # בדיקת כל התקצירים שפורסמו
python scripts/registry.py                        # עדכון רישום האירועים
node --test tests/engine.test.js                  # בדיקות הלמידה והדירוג
python -m unittest discover -s tests              # בדיקות הצנרת
python -m http.server 8765                        # צפייה מקומית: http://localhost:8765
```

יצירת תקציר ידנית עם Claude Code (מתוך התיקייה הזו):

```bash
claude "קרא את DIGEST_PROMPT.md ובצע את כל השלבים להיום"
```

אותו קובץ הוראות משמש גם את הריצה האוטומטית בענן (Claude Code routine), כך שהתוצאה זהה.

## עלויות: 0 ₪

| רכיב | ספק | למה זה חינם |
|---|---|---|
| אירוח האתר | GitHub Pages | חינם לריפו ציבורי |
| איסוף, מבזקים, בדיקות | GitHub Actions | ללא הגבלת דקות בריפו ציבורי; אין אמצעי תשלום בחשבון, ולכן אין אפשרות לחיוב |
| מקורות | RSS ציבורי + אתרים פתוחים | בלי API keys, בלי שירותי scraping, בלי עקיפת paywalls |
| כתיבת התקציר | Claude, במסגרת מנוי Pro קיים | צורך ממכסת המנוי בלבד |
| למידה אישית | הדפדפן של כל קורא (localStorage) | אין שרת ואין מסד נתונים |
| קוד | Python stdlib + JavaScript | בלי חבילות חיצוניות |

בדיקה אוטומטית (`tests/test_pipeline.py`, `NoPaidDependencies`) נכשלת אם מופיע בקוד OpenAI, Gemini, NewsAPI, Firebase, Supabase, Vercel, Netlify, שירות מייל או SMS, `api_key` או שימוש ב-secrets, ואם סקריפט מייבא ספרייה שאינה סטנדרטית.

**כדי לוודא שגם Claude לא יחייב:** ב-claude.ai, בהגדרות החשבון (Settings → Usage), ודאו ש-"Extra usage" כבוי. כך, אם מכסת המנוי נגמרת, הריצה פשוט נעצרת ולא מחייבת.

## מגבלות

- **הלמידה האישית נשמרת בדפדפן.** מעבר מכשיר מתחיל מאפס, ואין סנכרון בלי שרת.
- **"🧠 למד את המערכת" מפענח משפטים לפי מילות מפתח**, בלי AI. מה שלא זוהה נשמר כהערה גלויה. רק העורך (במצב `?admin=1`) יכול לשלוח הנחיה לסוכן, דרך GitHub issue.
- **רוב האתרים הרשמיים (gov.il ועוד) חוסמים גישה אוטומטית או לא מציעים RSS.** אימות רשמי נעשה רק כשהסוכן מצליח לפתוח את הדף.
- **הקיבוץ האוטומטי בסיסי**, לפי מילים משותפות בכותרות. הוא לא מאחד עברית ואנגלית, ואת האיחוד הסופי עושה הסוכן.
- **אין התראות push.** מבזקים מופיעים כבאנר בפתיחת האתר.

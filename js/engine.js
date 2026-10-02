/* Tamzit engine: everything that decides what a reader sees. Pure functions, no DOM,
   no network, no AI - runs in the browser and in Node tests (node --test tests/).

   Two separate scores per event:
     publicImportance  1-5, set by the editor/agent: how much the public needs to know.
     personalRelevance  learned per reader from 👍/👎 (+ reasons) and taught preferences.
   Personal taste can push an event down, but never hide something publicly important:
   high-importance events that a reader isn't into go to "חשוב לדעת" (anti-bubble). */
(function (root) {
  "use strict";

  const CATEGORIES = {
    security: "ביטחון", politics: "פוליטיקה", economy: "כלכלה", society: "חברה", law: "משפט",
    tech: "טכנולוגיה / AI", israel_world: "ישראל והעולם", world: "עולם", judaism: "יהדות",
    culture: "תרבות", sport: "ספורט"
  };
  const OLD_CATEGORY = { diplomacy: ["israel_world"], region: ["israel_world", "security"], health: ["society"] };
  const KINDS = {
    decision: "החלטה או צעד בפועל", event: "אירוע ביטחוני או אסון", statement: "הצהרה או איום",
    past: "חשיפה על העבר", dispute: "ויכוח ומחלוקת", data: "נתון או דוח",
    legal: "פסיקה או הליך משפטי", negotiation: "מגעים ומשא ומתן"
  };
  const NOISE = { gossip: "רכילות", celebrity: "סלבס", entertainment: "בידור", viral: "ויראלי / סערה ברשת", personal: "חדשות אישיות", clickbait: "קליקבייט", local: "חדשות מקומיות זניחות" };
  const STATUS = {
    VERIFIED: "מאומת", REPORTED: "דווח", CLAIM: "טענה", CONFLICTING: "דיווחים סותרים", UNCONFIRMED: "לא מאומת"
  };
  const MAIN_STATUS = ["VERIFIED", "REPORTED"];

  // 👎 reasons a reader can pick. Each maps to a targeted, stronger signal.
  const REASONS = {
    notimportant: "לא חשוב מספיק", gossip: "רכילות", celebrity: "סלבס", entertainment: "בידור",
    personal: "חדשות אישיות", topic: "נושא מסוים", source: "מקור מסוים", known: "כבר ידעתי את זה", other: "אחר"
  };

  const CAP = 5;            // max |weight| per feature
  const LOW = -1.5;         // personal relevance at or below this => "less relevant" fold
  const HIDE = -3;          // ...and at or below this (with low public importance) => not shown at all
  const KNOW_IMPORTANT = 4; // public importance that always stays visible
  const NOISE_PRIOR = -1;   // noise is down-weighted for everyone until the reader says otherwise

  function defaults() {
    return {
      v: 2, cats: Object.keys(CATEGORIES), minImp: 2, maxItems: 8, freq: "weekly",
      w: {}, votes: {}, reasons: {}, counts: {}, soft: {}, prefs: { changesOnly: [], showUnverified: [], lessRepeats: false },
      teach: [], mutedEntities: [], mutedIds: [], seen: {}, theme: "", dismissedAlert: ""
    };
  }

  // Bring state saved by older versions up to date (old category keys, old field names).
  function migrateState(s) {
    const d = defaults();
    s = Object.assign({}, d, s || {});
    s.prefs = Object.assign({}, d.prefs, s.prefs || {});
    if (s.mutedTags) { s.mutedEntities = Array.from(new Set([...(s.mutedEntities || []), ...s.mutedTags])); delete s.mutedTags; }
    const cats = new Set();
    (s.cats || []).forEach(c => (OLD_CATEGORY[c] || [c]).forEach(x => CATEGORIES[x] && cats.add(x)));
    if (!s.v || s.v < 2) ["israel_world", "world", "judaism", "culture", "sport"].forEach(c => cats.add(c));
    s.cats = Array.from(cats);
    const w = {};
    Object.entries(s.w || {}).forEach(([f, v]) => {
      if (f.startsWith("t:")) f = "e:" + f.slice(2);
      if (f.startsWith("c:") && OLD_CATEGORY[f.slice(2)]) { OLD_CATEGORY[f.slice(2)].forEach(c => { w["c:" + c] = (w["c:" + c] || 0) + v; }); return; }
      w[f] = (w[f] || 0) + v;
    });
    s.w = w;
    s.v = 2;
    return s;
  }

  // Accept both the new event schema (v2) and old "items" digests.
  function normalizeEvent(e, date) {
    const cats = e.categories || (OLD_CATEGORY[e.category] || [e.category]).filter(Boolean);
    return Object.assign({
      status: "REPORTED", change: "", entities: e.tags || [], noise: [], sourceCount: (e.sources || []).length,
      firstSeen: date, lastUpdated: date, kind: "", why: "", next: ""
    }, e, { categories: cats, entities: e.entities || e.tags || [] });
  }
  function normalizeDigest(d) {
    if (!d) return null;
    const date = d.date;
    return Object.assign({}, d, {
      events: (d.events || d.items || []).map(e => normalizeEvent(e, date)),
      unverified: (d.unverified || []).map(e => normalizeEvent(e, date))
    });
  }

  // ---- features & scores ----
  function features(e) {
    const f = [];
    if (e.kind) f.push("k:" + e.kind);
    (e.categories || []).forEach(c => f.push("c:" + c));
    (e.entities || []).forEach(t => f.push("e:" + t));
    (e.noise || []).forEach(n => f.push("n:" + n));
    return f;
  }
  const avg = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;

  function personalRelevance(e, s) {
    const w = s.w;
    let r = 0;
    if (e.kind) r += w["k:" + e.kind] || 0;
    const cw = (e.categories || []).map(c => w["c:" + c] || 0);
    if (cw.length) r += 0.7 * (Math.max(...cw) > 0 ? Math.max(...cw) : avg(cw));   // a liked category counts fully
    const ent = (e.entities || []).map(t => w["e:" + t] || 0);
    if (ent.length) r += ent.reduce((a, b) => a + b, 0) / Math.sqrt(ent.length);
    (e.noise || []).forEach(n => { r += NOISE_PRIOR + (w["n:" + n] || 0); });
    const src = (e.sources || []).map(x => w["s:" + x.name] || 0);
    if (src.length) r += 0.5 * Math.min(...src.concat([0])) * (src.every(v => v < 0) ? 1 : 0.3);
    r += w["imp:" + e.importance] || 0;
    // taught preference: in these categories, only real changes (decisions, laws, rulings, events)
    if ((e.categories || []).some(c => s.prefs.changesOnly.includes(c)) && ["statement", "dispute", "past"].includes(e.kind)) r -= 2;
    if (s.prefs.lessRepeats && e.change && e.change.length < 15) r -= 0.5;
    return Math.round(r * 100) / 100;
  }

  function clamp(v) { return Math.max(-CAP, Math.min(CAP, Math.round(v * 100) / 100)); }
  function bump(s, f, d) { s.w[f] = clamp((s.w[f] || 0) + d); if (s.w[f] === 0) delete s.w[f]; }

  // Plain 👍/👎: a gentle nudge on everything about the event. Repeated votes accumulate.
  const STEP = { k: 0.5, c: 0.4, e: 0.5, n: 0.6 };
  function nudge(e, s, dir) { features(e).forEach(f => bump(s, f, dir * STEP[f[0]])); }

  function vote(e, s, dir) {
    const prev = s.votes[e.id] || 0;
    if (prev) nudge(e, s, -prev);
    if (prev && s.soft && s.soft[e.id]) { nudge(e, s, -SOFTEN); delete s.soft[e.id]; }
    if (prev === dir) delete s.votes[e.id];
    else { nudge(e, s, dir); s.votes[e.id] = dir; }
    return s;
  }

  // 👎 + a reason: a targeted, stronger signal. `detail` = entity or source name for topic/source.
  // A specific reason explains the dislike, so the generic 👎 penalty on the item's
  // kind/category/entities is mostly taken back (otherwise five gossip dislikes would
  // also sink every unrelated "decision" item).
  const SOFTEN = 1, SPECIFIC = ["gossip", "celebrity", "entertainment", "personal", "topic", "source"];
  function applyReason(e, s, reason, detail) {
    s.reasons[e.id] = s.reasons[e.id] || [];
    if (s.reasons[e.id].includes(reason + (detail ? ":" + detail : ""))) return s;
    s.reasons[e.id].push(reason + (detail ? ":" + detail : ""));
    s.counts[reason] = (s.counts[reason] || 0) + 1;
    s.soft = s.soft || {};
    if (SPECIFIC.includes(reason) && s.votes[e.id] === -1 && !s.soft[e.id]) { nudge(e, s, SOFTEN); s.soft[e.id] = true; }
    switch (reason) {
      case "notimportant": bump(s, "imp:" + e.importance, -1); if (e.kind) bump(s, "k:" + e.kind, -0.5); break;
      case "gossip": case "celebrity": case "entertainment": case "personal": bump(s, "n:" + reason, -1.5); break;
      case "topic": if (detail) bump(s, "e:" + detail, -2); break;
      case "source": if (detail) bump(s, "s:" + detail, -2); break;
      case "known": if (s.counts.known >= 3) s.prefs.lessRepeats = true; break;
      default: break;
    }
    return s;
  }

  // ---- teaching in plain Hebrew (no AI: keyword rules; the text is also kept for the editor/agent) ----
  const CAT_WORDS = {
    security: ["ביטחון", "בטחון", "ביטחוני", "צבא", "צה\"ל", "מלחמה", "טרור", "פיגוע"],
    politics: ["פוליטיקה", "פוליטי", "בחירות", "כנסת", "ממשלה", "קואליציה", "אופוזיציה"],
    economy: ["כלכלה", "כלכלי", "מחירים", "שוק", "בורסה", "ריבית", "מיסים", "יוקר"],
    society: ["חברה", "חינוך", "בריאות", "רווחה"],
    law: ["משפט", "בג\"ץ", "בית המשפט", "חקיקה", "חוק"],
    tech: ["טכנולוגיה", "הייטק", "AI", "בינה מלאכותית", "סייבר"],
    israel_world: ["יחסי חוץ", "מדיניות חוץ", "ענייני חוץ", "דיפלומטיה", "דיפלומטי", "ישראל והעולם", "המדיני"],
    world: ["עולם", "בינלאומי", "חו\"ל"],
    judaism: ["יהדות", "דת", "רבנות"],
    culture: ["תרבות", "אמנות", "קולנוע", "מוזיקה"],
    sport: ["ספורט", "כדורגל", "כדורסל"]
  };
  const NOISE_WORDS = {
    gossip: ["רכילות", "גירושים", "גירושין", "זוגיות", "פרידה"],
    celebrity: ["מפורסמים", "סלבס", "סלבריטאים", "סלב", "ידוענים"],
    entertainment: ["בידור", "ריאליטי", "טלוויזיה"],
    viral: ["ויראלי", "סערה ברשת", "רשתות חברתיות", "טוויטר", "טיקטוק"]
  };
  const NEG = /(לא רוצה|לא מעניין|לא מעוניין|לא אכפת|בלי|פחות|אל ת|מספיק עם|לא צריך|לא להציג|תוריד|שונא)/;
  const POS = /(רוצה|מעניין אותי|מעוניין|יותר|חשוב לי|אוהב|תביא|תוסיף)/;

  function parseTeach(text) {
    const actions = [];
    const clauses = [];
    // sentences, then clauses ("X, אבל Y"); a clause without its own topic inherits the sentence's topic
    String(text || "").split(/[.\n;!?]+/).forEach(sentence => {
      let inherited = [];
      sentence.split(/,?\s+אבל\s+|,\s*(?=ו?לא\s|ו?רק\s|ו?גם\s)/).map(x => x.trim()).filter(Boolean).forEach(clause => {
        let cats = Object.keys(CAT_WORDS).filter(c => CAT_WORDS[c].some(w => clause.includes(w)));
        if (cats.length) inherited = cats; else cats = inherited;
        clauses.push({ clause, cats });
      });
    });
    clauses.forEach(({ clause, cats }) => {
      const noise = Object.keys(NOISE_WORDS).filter(n => NOISE_WORDS[n].some(w => clause.includes(w)));
      const onlyChanges = /רק (כש|כאשר|אם)?.{0,15}(שינוי|החלטה|חקיקה|חוק|מדיניות)|שינוי אמיתי|רק החלטות/.test(clause);
      const unverified = /(לא מאומת|שטרם אומת|לא מאושר|דיווחים לא)/.test(clause);
      const neg = NEG.test(clause) && !/(גם|רוצה לדעת גם)/.test(clause.replace(NEG, ""));
      if (onlyChanges) actions.push({ type: "changesOnly", cats: cats.length ? cats : Object.keys(CATEGORIES) });
      else if (unverified && !NEG.test(clause)) actions.push({ type: "showUnverified", cats: cats.length ? cats : Object.keys(CATEGORIES) });
      else {
        noise.forEach(n => actions.push({ type: "weight", feature: "n:" + n, delta: neg ? -3 : 1 }));
        if (!noise.length) cats.forEach(c => actions.push({ type: "weight", feature: "c:" + c, delta: neg ? -2 : (POS.test(clause) ? 2 : 0) }));
        if (/(כבר ידוע|חזרה על|אותו דבר|מידע ישן|שוב ושוב)/.test(clause)) actions.push({ type: "lessRepeats" });
      }
    });
    const seen = new Set();
    return actions.filter(a => a.type !== "weight" || a.delta !== 0).filter(a => {
      const k = JSON.stringify(a); if (seen.has(k)) return false; seen.add(k); return true;
    });
  }
  function applyTeach(text, s) {
    const actions = parseTeach(text);
    actions.forEach(a => {
      if (a.type === "weight") bump(s, a.feature, a.delta);
      if (a.type === "changesOnly") a.cats.forEach(c => s.prefs.changesOnly.includes(c) || s.prefs.changesOnly.push(c));
      if (a.type === "showUnverified") a.cats.forEach(c => s.prefs.showUnverified.includes(c) || s.prefs.showUnverified.push(c));
      if (a.type === "lessRepeats") s.prefs.lessRepeats = true;
    });
    s.teach.push({ text: String(text).trim(), at: new Date().toISOString().slice(0, 10), understood: actions.map(describeAction) });
    return { state: s, actions };
  }
  function describeAction(a) {
    const cl = (cats) => cats.length === Object.keys(CATEGORIES).length ? "בכל הנושאים" : "ב" + cats.map(c => CATEGORIES[c]).join(", ");
    if (a.type === "changesOnly") return `${cl(a.cats)}: רק כשיש שינוי אמיתי (החלטה, חקיקה, פסיקה, אירוע)`;
    if (a.type === "showUnverified") return `${cl(a.cats)}: להציג גם דיווחים שלא אומתו, מסומנים בבירור`;
    if (a.type === "lessRepeats") return "פחות חזרה על מידע שכבר ידוע";
    if (a.type === "weight") return `${a.delta > 0 ? "יותר" : "פחות"}: ${featureLabel(a.feature)}`;
    return "";
  }

  function featureLabel(f) {
    const v = f.slice(f.indexOf(":") + 1);
    if (f.startsWith("k:")) return KINDS[v] || v;
    if (f.startsWith("c:")) return CATEGORIES[v] || v;
    if (f.startsWith("n:")) return NOISE[v] || v;
    if (f.startsWith("s:")) return "המקור " + v;
    if (f.startsWith("imp:")) return "ידיעות בחשיבות " + v + "/5";
    return v;
  }

  // ---- deciding what goes where ----
  function hardHidden(e, s) {
    if (s.mutedIds.includes(e.id)) return true;
    if (!(e.categories || []).some(c => s.cats.includes(c)) && (e.importance || 0) < KNOW_IMPORTANT) return true;
    if ((e.entities || []).some(t => s.mutedEntities.includes(t)) && (e.importance || 0) < 5) return true;
    return false;
  }

  /* Returns { main, knowImportant, unverified, low, seen, hidden } for one digest view.
     seenBefore: map id -> lastUpdated the reader already saw on an EARLIER day. */
  function buildSections(digest, s, seenBefore) {
    seenBefore = seenBefore || {};
    const out = { main: [], knowImportant: [], unverified: [], low: [], seen: [], hidden: [] };
    if (!digest) return out;
    const all = dedupe((digest.events || []).concat(digest.unverified || []));
    const scored = all.map(e => ({ e, rel: personalRelevance(e, s) }));
    scored.sort((a, b) => ((b.e.importance || 0) + 0.8 * b.rel) - ((a.e.importance || 0) + 0.8 * a.rel));
    const pool = [];
    scored.forEach(({ e, rel }) => {
      const x = Object.assign({}, e, { _rel: rel });
      if (hardHidden(e, s)) return out.hidden.push(x);
      // a claim is never shown as a fact, even if the data put it in the wrong list
      if (!MAIN_STATUS.includes(e.status) || (digest.unverified || []).some(u => u.id === e.id)) {
        const wanted = (e.categories || []).some(c => s.prefs.showUnverified.includes(c));
        if ((e.importance || 0) >= KNOW_IMPORTANT || wanted) out.unverified.push(x); else out.hidden.push(x);
        return;
      }
      const seen = seenBefore[e.id];
      if (seen && seen >= (e.lastUpdated || "")) return out.seen.push(x);          // nothing new since they read it
      if (s.votes[e.id] === -1 && (e.importance || 0) < KNOW_IMPORTANT) return out.low.push(x);
      if (rel <= LOW && s.votes[e.id] !== 1) {
        if ((e.importance || 0) >= KNOW_IMPORTANT) return out.knowImportant.push(x);  // anti-bubble
        if (rel <= HIDE) return out.hidden.push(x);
        return out.low.push(x);
      }
      if ((e.importance || 0) < s.minImp) return out.low.push(x);
      pool.push(x);
    });
    out.main = pool.slice(0, s.maxItems);
    out.low = pool.slice(s.maxItems).concat(out.low);
    out.knowImportant = out.knowImportant.slice(0, 3);
    return out;
  }

  // Safety net: the same event twice (same id, or near-identical titles) is shown once.
  function titleTokens(t) {
    return new Set(String(t || "").toLowerCase().replace(/[^\w֐-׿\s]/g, " ").split(/\s+/).filter(w => w.length > 2));
  }
  function dedupe(events) {
    const out = [];
    events.forEach(e => {
      const tk = titleTokens(e.title);
      const dup = out.find(o => o.id === e.id || (() => {
        const ot = titleTokens(o.title); let inter = 0; tk.forEach(w => ot.has(w) && inter++);
        return inter >= 3 && inter / Math.max(1, Math.min(tk.size, ot.size)) >= 0.6;
      })());
      if (!dup) out.push(Object.assign({}, e));
      else if ((e.lastUpdated || "") > (dup.lastUpdated || "")) out[out.indexOf(dup)] = Object.assign({}, e, { sources: mergeSources(dup.sources, e.sources) });
      else dup.sources = mergeSources(dup.sources, e.sources);
    });
    return out;
  }
  function mergeSources(a, b) {
    const seen = new Set(), out = [];
    (a || []).concat(b || []).forEach(x => { if (!seen.has(x.url)) { seen.add(x.url); out.push(x); } });
    return out;
  }

  // "השבוע": combine this week's daily digests into one, one entry per event (latest version wins).
  function rollupWeek(digests) {
    const sorted = digests.filter(Boolean).slice().sort((a, b) => a.date < b.date ? -1 : 1);
    const byId = new Map(), unv = new Map();
    sorted.forEach(d => {
      (d.events || []).forEach(e => {
        const prev = byId.get(e.id);
        const changes = prev ? (prev._changes || []).concat(e.change ? [{ date: d.date, text: e.change }] : []) : [];
        byId.set(e.id, Object.assign({}, e, {
          importance: Math.max(e.importance || 0, prev ? prev.importance : 0),
          firstSeen: prev ? prev.firstSeen : e.firstSeen, sources: mergeSources(prev && prev.sources, e.sources),
          _changes: changes
        }));
        unv.delete(e.id);
      });
      (d.unverified || []).forEach(e => { if (!byId.has(e.id)) unv.set(e.id, e); });
    });
    const last = sorted[sorted.length - 1];
    return {
      schema: 2, type: "weekly-rollup", date: last ? last.date : "", from: sorted.length ? sorted[0].date : "",
      headline: "", events: Array.from(byId.values()), unverified: Array.from(unv.values()),
      filtered_out: sorted.reduce((a, d) => a + (d.filtered_out || 0), 0)
    };
  }

  // ---- "ⓘ למה זה כאן?" (plain language, never the internal numbers) ----
  function explain(e, s, section) {
    const why = [];
    if (section === "knowImportant") why.push("מוצג למרות שזה פחות בתחומי העניין שלך, כי זה חשוב ציבורית");
    else if ((e.importance || 0) >= 4) why.push("חשיבות ציבורית גבוהה");
    if ((e.categories || []).includes("israel_world") || /ישראל/.test(e.why || "")) why.push("האירוע משפיע על ישראל");
    if (e.sourceCount >= 2) why.push(`דווח על ידי ${e.sourceCount} מקורות`);
    if ((e.sources || []).some(x => x.tier === 1 || x.type === "official")) why.push("קיימת הודעה רשמית");
    if (e.status === "VERIFIED") why.push("אומת במספר מקורות בלתי תלויים");
    if (e.change && section !== "seen") why.push("יש התפתחות חדשה מאז העדכון הקודם");
    const likedCats = (e.categories || []).filter(c => (s.w["c:" + c] || 0) >= 1);
    if (likedCats.length) why.push("מתאים לתחום " + likedCats.map(c => CATEGORIES[c]).join(", ") + " שלך");
    const likedEnt = (e.entities || []).filter(t => (s.w["e:" + t] || 0) >= 1);
    if (likedEnt.length) why.push("עוסק ב" + likedEnt.slice(0, 2).join(", ") + ", שסימנת כמעניין");
    if (section === "unverified") why.push("מוצג בנפרד כי טרם אומת");
    if (section === "low") why.push("הורד למטה לפי הסימונים שלך");
    if (s.votes[e.id] === 1) why.push("סימנת שזה מעניין אותך");
    return why.length ? why : ["אירוע מרכזי של היום לפי בחירת העורך"];
  }

  // ---- "מה למדתי עליך" ----
  function learnedSummary(s) {
    const level = v => v >= 2 ? "גבוה" : v >= 0.5 ? "בינוני" : null;
    const important = Object.keys(CATEGORIES).map(c => ({ f: "c:" + c, label: CATEGORIES[c], lvl: level(s.w["c:" + c] || 0) }))
      .filter(x => x.lvl).sort((a, b) => (s.w[b.f] || 0) - (s.w[a.f] || 0));
    Object.entries(s.w).filter(([f, v]) => f.startsWith("e:") && v >= 1).sort((a, b) => b[1] - a[1]).slice(0, 5)
      .forEach(([f, v]) => important.push({ f, label: featureLabel(f), lvl: level(v) }));
    const less = Object.entries(s.w).filter(([, v]) => v <= -1).sort((a, b) => a[1] - b[1]).slice(0, 10)
      .map(([f]) => ({ f, label: featureLabel(f) }));
    const prefs = [];
    if (s.prefs.lessRepeats || (s.counts.known || 0) >= 2) prefs.push("מעוניין בהתפתחויות ולא בחזרה על מידע קיים");
    if (s.prefs.changesOnly.length) prefs.push(describeAction({ type: "changesOnly", cats: s.prefs.changesOnly }));
    if (s.prefs.showUnverified.length) prefs.push(describeAction({ type: "showUnverified", cats: s.prefs.showUnverified }));
    if ((s.w["c:israel_world"] || 0) >= 1 || (s.w["c:world"] || 0) <= -1) prefs.push("מעדיף אירועים עם משמעות לישראל");
    return { important, less, prefs, teach: s.teach.slice() };
  }
  function forget(s, what) {
    if (what === "all") return Object.assign(defaults(), { cats: s.cats, theme: s.theme, minImp: s.minImp, maxItems: s.maxItems, freq: s.freq, seen: s.seen });
    if (what.startsWith("pref:")) {
      const p = what.slice(5);
      if (p === "lessRepeats") { s.prefs.lessRepeats = false; s.counts.known = 0; }
      else s.prefs[p] = [];
      return s;
    }
    if (what.startsWith("teach:")) { s.teach.splice(+what.slice(6), 1); return s; }
    delete s.w[what];
    return s;
  }

  const api = {
    CATEGORIES, KINDS, NOISE, STATUS, REASONS, MAIN_STATUS, LOW, HIDE, KNOW_IMPORTANT,
    defaults, migrateState, normalizeDigest, normalizeEvent, features, personalRelevance, vote, applyReason,
    parseTeach, applyTeach, describeAction, featureLabel, buildSections, dedupe, rollupWeek, explain, learnedSummary, forget
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Engine = api;
})(typeof self !== "undefined" ? self : this);

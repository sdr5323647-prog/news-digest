// Run: node --test tests/   (Node's built-in test runner, no packages needed)
const test = require("node:test");
const assert = require("node:assert/strict");
const E = require("../js/engine.js");

const src = (name, tier = 2, type = "reporting") => ({ name, url: `https://${name}.example/a`, tier, type });
function ev(id, o = {}) {
  return Object.assign({
    id, title: "כותרת " + id, summary: "סיכום של " + id, why: "", change: "", status: "VERIFIED", importance: 3,
    categories: ["politics"], kind: "decision", entities: [], noise: [], sources: [src("a"), src("b")], sourceCount: 2,
    firstSeen: "2026-10-03", lastUpdated: "2026-10-03"
  }, o);
}
const digest = (events, unverified = []) => E.normalizeDigest({ schema: 2, date: "2026-10-03", type: "daily", events, unverified });
const ids = (arr) => arr.map(e => e.id);
const fresh = () => E.migrateState({});

test("1+2: marking gossip as not interesting keeps similar gossip out of the reader's digest", () => {
  let s = fresh();
  const g1 = ev("celeb-divorce", { categories: ["culture"], kind: "event", noise: ["gossip", "celebrity"], importance: 2, entities: ["סלב א"] });
  for (let i = 0; i < 5; i++) {
    const g = ev("gossip-" + i, { categories: ["culture"], noise: ["gossip"], importance: 2 });
    E.vote(g, s, -1); E.applyReason(g, s, "gossip");
  }
  const sec = E.buildSections(digest([g1, ev("budget")]), s);
  assert.ok(!ids(sec.main).includes("celeb-divorce"), "gossip must not be in main");
  assert.ok(ids(sec.hidden).includes("celeb-divorce"), "after 5 'gossip' marks similar gossip is not shown at all");
  assert.ok(ids(sec.main).includes("budget"));
});

test("undoing a 👎 that had a reason leaves no trace", () => {
  const s = fresh();
  const g = ev("g", { noise: ["gossip"], entities: ["x"] });
  E.vote(g, s, -1); E.applyReason(g, s, "gossip"); E.vote(g, s, -1);   // press 👎 again = cancel
  const left = Object.entries(s.w).filter(([f]) => f !== "n:gossip");  // the explicit reason itself is kept
  assert.deepEqual(left, []);
});

test("3+4: liking security raises relevance of security events", () => {
  const s = fresh();
  const sec1 = ev("strike", { categories: ["security"], kind: "event" });
  const before = E.personalRelevance(sec1, s);
  for (let i = 0; i < 3; i++) E.vote(ev("sec-" + i, { categories: ["security"], kind: "event" }), s, 1);
  const after = E.personalRelevance(sec1, s);
  assert.ok(after > before + 1, `relevance should rise clearly (${before} -> ${after})`);
  const order = ids(E.buildSections(digest([ev("econ", { categories: ["economy"], importance: 3 }), sec1]), s).main);
  assert.equal(order[0], "strike", "security event ranks first for this reader");
});

test("5: a publicly important event never disappears because of personal taste", () => {
  const s = fresh();
  for (let i = 0; i < 6; i++) E.vote(ev("p" + i, { categories: ["economy"], kind: "data" }), s, -1);
  const big = ev("rate-hike", { categories: ["economy"], kind: "data", importance: 5 });
  const imp4 = ev("budget-cut", { categories: ["economy"], kind: "data", importance: 4 });
  const sec = E.buildSections(digest([big, imp4]), s);
  const visible = ids(sec.main).concat(ids(sec.knowImportant));
  assert.ok(visible.includes("rate-hike") && visible.includes("budget-cut"), JSON.stringify(sec, (k, v) => k === "sources" ? undefined : v));
  assert.ok(ids(sec.knowImportant).length >= 1, "shown under 'חשוב לדעת'");
  assert.ok(E.explain(sec.knowImportant[0], s, "knowImportant")[0].includes("חשוב ציבורית"));
});

test("6: the same event from several outlets / duplicate entries is shown once", () => {
  const a = ev("flydubai-attack", { title: "טייס משנה דקר את הקברניט בטיסת פליידובאי לתל אביב" });
  const b = ev("flydubai-attack-2", { title: "בטיסת פליידובאי לתל אביב: טייס משנה דקר את הקברניט", sources: [src("c"), src("d"), src("e")] });
  const c = ev("flydubai-attack", { lastUpdated: "2026-10-03" });
  const sec = E.buildSections(digest([a, b, c]), fresh());
  assert.equal(sec.main.length, 1);
  assert.ok(sec.main[0].sources.length >= 4, "sources from the duplicates are merged");
});

test("7: an event the reader already saw is only shown again if it changed", () => {
  const s = fresh();
  const old = ev("us-iran-talks", { lastUpdated: "2026-10-01", firstSeen: "2026-10-01" });
  const upd = ev("balad", { lastUpdated: "2026-10-03", firstSeen: "2026-10-01", change: "אבו שחאדה הסיר את מועמדותו" });
  const seenBefore = { "us-iran-talks": "2026-10-01", "balad": "2026-10-01" };
  const sec = E.buildSections(digest([old, upd]), s, seenBefore);
  assert.deepEqual(ids(sec.seen), ["us-iran-talks"]);
  assert.deepEqual(ids(sec.main), ["balad"]);
  assert.ok(E.explain(sec.main[0], s, "main").some(x => x.includes("התפתחות חדשה")));
});

test("8+9: claims and unverified reports never appear as facts in the main news", () => {
  const s = fresh();
  const claim = ev("hamas-claim", { status: "CLAIM", importance: 4, summary: "חמאס טען כי..." });
  const weak = ev("rumor", { status: "UNCONFIRMED", importance: 2 });
  const misfiled = ev("misfiled", { status: "CONFLICTING", importance: 4 });
  const sec = E.buildSections(digest([misfiled, ev("fact")], [claim, weak]), s);
  assert.deepEqual(ids(sec.main), ["fact"]);
  assert.deepEqual(ids(sec.unverified).sort(), ["hamas-claim", "misfiled"]);
  assert.ok(ids(sec.hidden).includes("rumor"), "low-importance unverified items are not shown by default");
});

test("8b: a reader who asked for unverified security reports gets them, still separated", () => {
  const s = fresh();
  E.applyTeach("בביטחון אני רוצה לדעת גם על דיווחים לא מאומתים, אבל שיהיה כתוב בבירור", s);
  const sec = E.buildSections(digest([], [ev("rumor", { status: "UNCONFIRMED", importance: 2, categories: ["security"] })]), s);
  assert.deepEqual(ids(sec.unverified), ["rumor"]);
  assert.equal(sec.main.length, 0);
});

test("10: the reader can see why a story was chosen, without numbers", () => {
  const s = fresh();
  for (let i = 0; i < 3; i++) E.vote(ev("s" + i, { categories: ["security"] }), s, 1);
  const e = ev("x", { categories: ["security", "israel_world"], importance: 4, sourceCount: 4, sources: [src("a"), src("idf", 1, "official")] });
  const why = E.explain(e, s, "main");
  ["חשיבות ציבורית גבוהה", "משפיע על ישראל", "דווח על ידי 4 מקורות", "הודעה רשמית", "ביטחון"].forEach(w =>
    assert.ok(why.some(x => x.includes(w)), `missing reason: ${w} in ${why}`));
  assert.ok(!why.join(" ").match(/\d\.\d|score|ציון/), "no internal numbers");
});

test("11: learning can be reset (all, or one item)", () => {
  let s = fresh();
  E.vote(ev("a", { categories: ["security"] }), s, 1);
  E.applyTeach("אני לא רוצה רכילות על מפורסמים", s);
  assert.ok(Object.keys(s.w).length > 0 && s.teach.length === 1);
  s = E.forget(s, "n:gossip");
  assert.ok(!("n:gossip" in s.w));
  s = E.forget(s, "all");
  assert.deepEqual(s.w, {}); assert.deepEqual(s.votes, {}); assert.equal(s.teach.length, 0);
});

test("teach: plain Hebrew sentences become preferences", () => {
  const a1 = E.parseTeach("אני רוצה פוליטיקה רק כשיש שינוי אמיתי במדיניות או בחקיקה.");
  assert.deepEqual(a1, [{ type: "changesOnly", cats: ["politics", "law"] }]);
  const a2 = E.parseTeach("אני לא רוצה רכילות על מפורסמים.");
  assert.deepEqual(a2.map(a => a.feature).sort(), ["n:celebrity", "n:gossip"]);
  assert.ok(a2.every(a => a.delta < 0));
  const a3 = E.parseTeach("בביטחון אני רוצה לדעת גם על דיווחים לא מאומתים, אבל שיהיה כתוב בבירור שהם לא מאומתים.");
  assert.deepEqual(a3, [{ type: "showUnverified", cats: ["security"] }], "the 'אבל' half inherits the topic, no duplicate 'all topics' rule");
  const s = fresh(); E.applyTeach("אני רוצה פוליטיקה רק כשיש שינוי אמיתי במדיניות או בחקיקה.", s);
  const talk = ev("talk", { categories: ["politics"], kind: "dispute" });
  const law = ev("law", { categories: ["politics"], kind: "decision" });
  assert.ok(E.personalRelevance(talk, s) < E.personalRelevance(law, s) - 1);
});

test("reasons: topic and source reasons target only that topic/source", () => {
  const s = fresh();
  const e = ev("n", { entities: ["נתניהו", "7 באוקטובר"], kind: "past", sources: [src("tabloid", 2)] });
  E.vote(e, s, -1); E.applyReason(e, s, "topic", "7 באוקטובר"); E.applyReason(e, s, "source", "tabloid");
  assert.ok(s.w["e:7 באוקטובר"] <= -2, "the chosen topic is penalised");
  assert.equal(s.w["e:נתניהו"] || 0, 0, "the other entity of the same story is NOT penalised");
  assert.equal(s.w["k:past"] || 0, 0, "the reason explains the dislike, so the kind isn't blamed");
  assert.ok(s.w["s:tabloid"] < 0);
  for (let i = 0; i < 3; i++) E.applyReason(ev("k" + i), s, "known");
  assert.ok(s.prefs.lessRepeats);
  assert.ok(E.learnedSummary(s).prefs.some(p => p.includes("התפתחויות")));
});

test("week view: dailies roll up into one entry per event with its changes", () => {
  const d1 = { date: "2026-10-01", events: [ev("flydubai-attack", { importance: 5, lastUpdated: "2026-10-01" })] };
  const d2 = { date: "2026-10-02", events: [ev("flydubai-attack", { importance: 4, change: "הטייס הועבר לחקירה", lastUpdated: "2026-10-02" }), ev("other")] };
  const w = E.rollupWeek([d2, d1]);
  assert.equal(w.events.length, 2);
  const f = w.events.find(e => e.id === "flydubai-attack");
  assert.equal(f.importance, 5); assert.equal(f.lastUpdated, "2026-10-02"); assert.equal(f._changes.length, 1);
});

test("old saved state and old digests still work", () => {
  const s = E.migrateState({ cats: ["security", "diplomacy", "region"], w: { "t:איראן": 2, "c:region": -1 }, mutedTags: ["סקרים"] });
  assert.ok(s.cats.includes("israel_world") && s.cats.includes("security"));
  assert.equal(s.w["e:איראן"], 2); assert.equal(s.w["c:israel_world"], -1);
  assert.deepEqual(s.mutedEntities, ["סקרים"]);
  const d = E.normalizeDigest({ date: "2026-09-30", items: [{ id: "x", title: "t", summary: "s", category: "region", importance: 3, tags: ["איראן"], sources: [] }] });
  assert.deepEqual(d.events[0].categories, ["israel_world", "security"]);
  assert.deepEqual(d.events[0].entities, ["איראן"]);
});

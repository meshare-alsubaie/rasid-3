// اختبارات منطق التطبيق: node --test app/
import { test } from "node:test";
import assert from "node:assert/strict";
import { matchScore, daysAr, countdown } from "./core.js";

const ME = { major: "علوم حاسب", interests: ["أمن"], hasCourses: true, city: null };
const ent = (o = {}) => ({ id: "x", name: "جهة", cyber: 1, fulltime_history: "unknown", ...o });
const prog = (fields = {}, majors = []) => ({ fields, majors });
const F = v => ({ value: v, quote: "q" });

test("مثال المؤسس: أحياء ٤ مقاعد وعلوم حاسب مقعدين تعطي نسبة متناسبة", () => {
  const p = prog({}, [{ name: "الأحياء", seats: 4 }, { name: "علوم الحاسب", seats: 2 }]);
  const r = matchScore(p, ent(), { ...ME, hasCourses: false });
  assert.ok(r.pct >= 25 && r.pct <= 45, `pct=${r.pct}`);
  assert.ok(r.reasons.some(s => s.includes("مقعدين") || s.includes("2")));
});

test("مفتوح لكل التخصصات يعتبر مناسباً (خطأ راصد ٢ القاتل)", () => {
  const r = matchScore(prog({ open_to_all_majors: F(true) }), ent(), { ...ME, hasCourses: false });
  assert.ok(r.pct >= 80, `pct=${r.pct}`);
  assert.ok(r.reasons.some(s => s.includes("لكل التخصصات")));
});

test("سدايا تطلب علوم حاسب وقريبة من الأمن ترتفع جداً", () => {
  const p = prog({}, [{ name: "علوم الحاسب", seats: 10 }]);
  const r = matchScore(p, ent({ cyber: 3 }), { ...ME, hasCourses: false });
  assert.ok(r.pct >= 95, `pct=${r.pct}`);
});

test("التخصص غير مطلوب يعطي نسبة منخفضة لكن غير صفرية", () => {
  const r = matchScore(prog({}, [{ name: "المحاسبة", seats: 5 }]), ent(), { ...ME, hasCourses: false });
  assert.ok(r.pct > 0 && r.pct < 30, `pct=${r.pct}`);
});

test("التخصصات غير مذكورة: نسبة وسط مع سبب صريح", () => {
  const r = matchScore(prog(), ent(), { ...ME, hasCourses: false });
  assert.ok(r.pct >= 45 && r.pct <= 75);
  assert.ok(r.reasons.some(s => s.includes("غير مذكورة")));
});

test("اشتراط التفرغ مع وجود مواد: تحذير أحمر ونسبة تنزل", () => {
  const p = prog({ open_to_all_majors: F(true), no_courses_allowed: F(true) });
  const withCourses = matchScore(p, ent(), ME), without = matchScore(p, ent(), { ...ME, hasCourses: false });
  assert.ok(withCourses.pct < without.pct / 2);
  assert.ok(withCourses.warning && withCourses.warning.includes("التفرّغ"));
  assert.equal(without.warning, null);
});

test("جهة ما اشترطت التفرغ نصاً سابقاً تبرز: فرصتك أعلى", () => {
  const r = matchScore(prog({ open_to_all_majors: F(true) }), ent({ fulltime_history: "no" }), ME);
  assert.ok(r.reasons.some(s => s.includes("فرصتك أعلى")));
});

test("النسبة دائماً بين ٠ و١٠٠ وعدد صحيح", () => {
  const r = matchScore(prog({ open_to_all_majors: F(true) }, [{ name: "علوم الحاسب", seats: 3 }]), ent({ cyber: 3 }), ME);
  assert.ok(Number.isInteger(r.pct) && r.pct >= 0 && r.pct <= 100);
});

test("الأيام بعربي سليم", () => {
  assert.equal(daysAr(1), "يوم واحد"); assert.equal(daysAr(2), "يومين");
  assert.equal(daysAr(8), "8 أيام"); assert.equal(daysAr(21), "21 يوماً");
});

test("العد التنازلي يطابق رسائل تيليجرام", () => {
  const today = "2026-10-25";
  assert.equal(countdown("2026-10-26", "2026-11-02", today), "يفتح بعد يوم واحد، باقي 8 أيام على الإغلاق");
  assert.equal(countdown("2026-10-26", "2026-11-02", "2026-11-02"), "مفتوح الآن، آخر يوم للتقديم اليوم");
  assert.equal(countdown("2026-10-26", "2026-11-02", "2026-11-05"), "أقفل التقديم");
});

test("المحاسبة والمحاسب ليست علوم حاسب، والحاسب الآلي هي", () => {
  const acc = matchScore(prog({}, [{ name: "المحاسبة" }, { name: "محاسب قانوني" }]), ent(), { ...ME, hasCourses: false });
  const cs = matchScore(prog({}, [{ name: "الحاسب الآلي" }]), ent(), { ...ME, hasCourses: false });
  assert.ok(acc.pct < 30 && cs.pct >= 80, `acc=${acc.pct} cs=${cs.pct}`);
});

// منطق التطبيق الصافي (بلا واجهة): نسبة المناسبة، العد التنازلي، الأيام بعربي سليم.
// يُحسب في جهاز كل مستخدم فقط؛ تخصصه وظروفه لا تغادر جهازه أبداً.

// «حاسب» بشرط ألا تسبقها «م» (المحاسبة والمحاسب ليست علوم حاسب)
const CS = /(?<!م)حاسب|حاسوب|computer|معلومات|information|برمجيات|software|سيبران|cyber|أمن المعلومات|بيانات|data|ذكاء|artificial|شبكات|network/i;
const INTEREST_BONUS = 0.15;
const FULLTIME_PENALTY = 0.35;

function plural(n, one, two, few, many) {
  if (n === 1) return one;
  if (n === 2) return two;
  return n >= 3 && n <= 10 ? `${n} ${few}` : `${n} ${many}`;
}
export const daysAr = n => plural(n, "يوم واحد", "يومين", "أيام", "يوماً");
const seatsAr = n => plural(n, "مقعد واحد", "مقعدين", "مقاعد", "مقعداً");
const val = (p, k) => p?.fields?.[k]?.value ?? null;

function majorFit(p) {
  if (val(p, "open_to_all_majors") === true) return { fit: 1, reason: "مفتوح لكل التخصصات" };
  const majors = p?.majors ?? [];
  if (!majors.length) return { fit: 0.6, reason: "التخصصات غير مذكورة في الإعلان" };
  const mine = majors.filter(m => CS.test(m.name));
  if (!mine.length) return { fit: 0.12, reason: "ما طلبت تخصصك" };
  if (majors.every(m => Number.isFinite(m.seats))) {
    const total = majors.reduce((s, m) => s + m.seats, 0), got = mine.reduce((s, m) => s + m.seats, 0);
    return { fit: Math.max(0.12, got / total), reason: `طلبت تخصصك: ${seatsAr(got)} من ${total}` };
  }
  return { fit: 0.85, reason: "طلبت تخصصك" };
}

export function matchScore(program, entity, profile) {
  const reasons = [];
  const { fit, reason } = majorFit(program);
  let score = fit;
  reasons.push(reason);
  if (profile.interests?.includes("أمن") && entity.cyber > 0) {
    score += INTEREST_BONUS * (entity.cyber / 3);
    if (entity.cyber === 3) reasons.push("قريبة جداً من الأمن السيبراني");
  }
  if (entity.fulltime_history === "no") { score += 0.05; reasons.push("ما اشترطت التفرّغ نصاً سابقاً، فرصتك أعلى"); }
  if (entity.fulltime_history === "yes") reasons.push("اشترطت التفرّغ في سنوات سابقة");
  let warning = null;
  if (profile.hasCourses && val(program, "no_courses_allowed") === true) {
    score *= FULLTIME_PENALTY;
    warning = "تشترط التفرّغ ومعك مواد: ظرفك ما يناسبها";
  }
  const cities = val(program, "cities");
  if (profile.city && Array.isArray(cities) && cities.length && !cities.includes(profile.city) && val(program, "housing") !== true) {
    score *= 0.8; reasons.push(`في ${cities.join(" و")} بدون سكن`);
  }
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  return { pct, reasons, warning };
}

const dayDiff = (iso, today) => Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);

export function countdown(opens, closes, today) {
  if (closes && dayDiff(closes, today) < 0) return "أقفل التقديم";
  const parts = [];
  if (opens && dayDiff(opens, today) > 0) parts.push(`يفتح بعد ${daysAr(dayDiff(opens, today))}`);
  else if (opens || closes) parts.push("مفتوح الآن");
  if (closes) {
    const left = dayDiff(closes, today);
    parts.push(left === 0 ? "آخر يوم للتقديم اليوم" : `باقي ${daysAr(left)} على الإغلاق`);
  }
  return parts.join("، ");
}

// الملف الشخصي الافتراضي (يُحفظ في جهاز المستخدم فقط ويقدر يغيّره)
export const DEFAULT_PROFILE = Object.freeze({
  major: "علوم حاسب", interests: ["أمن"], hasCourses: true, city: null, minStars: 3, showJobs: false,
});

export function isStale(generatedAt, now = new Date(), hours = 12) {
  return now - new Date(generatedAt) > hours * 3600000;
}

const STATUS_ORDER = { closing_soon: 0, open: 1, announced: 2, listed: 3 };

// قائمة البطاقات: المفتوح ثم القادم، ثم الأعلى مناسبة. بلا المنتهي، وبحد النجوم، والوظائف اختيارية.
export function rankPrograms(results, profile, today) {
  const ents = Object.fromEntries(results.entities.map(e => [e.id, e]));
  return results.programs
    .filter(p => p.status !== "closed" && !(p.closes && p.closes < today))
    .filter(p => p.family === "student" || (profile.showJobs && (p.family === "job" || p.family === "grad")))
    .filter(p => (ents[p.entity]?.stars ?? 0) >= profile.minStars)
    .map(p => ({ program: p, entity: ents[p.entity], match: matchScore(p, ents[p.entity], profile) }))
    .sort((a, b) => (STATUS_ORDER[a.program.status] ?? 9) - (STATUS_ORDER[b.program.status] ?? 9) || b.match.pct - a.match.pct);
}

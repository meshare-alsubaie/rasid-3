// واجهة التطبيق: تقرأ results.json العام وتعرضه حسب ظروف المستخدم المحفوظة في جهازه.
import { DEFAULT_PROFILE, countdown, isStale, matchScore, rankPrograms } from "./core.js";

const KIND = { coop: "تدريب تعاوني", university: "تدريب جامعي", hint: "تلميح لبرنامج قادم",
               grad_program: "برنامج لحديثي التخرج", job: "وظيفة" };
const STATUS = { not_announced: "لم تعلن بعد", announced: "أعلنت، وقريباً يفتح", open: "مفتوح الآن",
                 closing_soon: "يقفل قريباً", closed: "أقفل", listed: "صفحة البرنامج متاحة" };
const MONTHS = ["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"];
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Riyadh" });
const fmt = iso => { const d = new Date(iso + "T00:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };

// التخزين المحلي قد يكون محجوباً (تصفح خاص)، فكل قراءة وكتابة محمية
const store = {
  get(k, fallback) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* يكمل بدون حفظ */ } },
};
let profile = { ...DEFAULT_PROFILE, ...store.get("profile", {}) };
const applied = new Set(store.get("applied", []));
let results = null;

async function load() {
  try {
    const r = await fetch("results.json", { cache: "no-cache" });
    results = await r.json();
  } catch {
    $("#stale").hidden = false;
    $("#stale").textContent = "تعذّر تحميل النتائج. تأكد من الإنترنت ثم افتح التطبيق مرة ثانية.";
    return;
  }
  if (isStale(results.generated_at)) {
    $("#stale").hidden = false;
    $("#stale").textContent = "راصد ما تحدّث من أكثر من ١٢ ساعة. تابع مواقع الجهات بنفسك احتياطاً حتى يرجع.";
  }
  render();
  openFromHash();
}

function card({ program: p, entity: e, match: m }) {
  const cd = countdown(p.opens, p.closes, today());
  const done = applied.has(p.key);
  return `<article class="card ${done ? "done" : ""}" data-entity="${esc(e.id)}" tabindex="0">
    <div class="who">${esc(e.name)}</div>
    <div class="kind">${esc(KIND[p.kind] || "")}${p.title ? "، " + esc(p.title) : ""}</div>
    <div class="count">${esc(cd || STATUS[p.status] || "")}</div>
    <div class="match"><b>${m.pct}٪</b> ${esc(m.reasons[0] || "")}</div>
    ${m.warning ? `<span class="warn">${esc(m.warning)}</span>` : ""}
    ${p.kind === "university" ? `<span class="note">تأكّد من جامعتك هل يُحتسب تعاونياً</span>` : ""}
    ${done ? `<span class="badge">قدّمت</span>` : ""}
  </article>`;
}

function render() {
  const ranked = rankPrograms(results, profile, today());
  $("#live").innerHTML = ranked.length ? ranked.map(card).join("")
    : `<p class="empty">ما فيه برامج مفتوحة أو قادمة الآن حسب ظروفك. راصد يراقب ${results.entities.length} جهة ويرسل لك أول ما يُعلن.</p>`;
  const q = $("#search").value.trim();
  $("#all").innerHTML = results.entities
    .filter(e => !q || e.name.includes(q))
    .sort((a, b) => b.stars - a.stars || a.name.localeCompare(b.name, "ar"))
    .map(e => `<li><button data-entity="${esc(e.id)}">
        <span class="name">${esc(e.name)}</span>
        <span class="stars" aria-label="${e.stars} نجوم">${"★".repeat(e.stars)}</span>
        <span class="st st-${esc(e.status)}">${esc(STATUS[e.status])}</span>
        ${e.sources_ok < e.sources_total ? `<span class="health">${e.sources_ok} من ${e.sources_total} مصادر تُقرأ</span>` : ""}
      </button></li>`).join("");
}

function entityView(id) {
  const e = results.entities.find(x => x.id === id);
  if (!e) return null;
  const p = results.programs.find(x => x.key === e.program);
  const m = p ? matchScore(p, e, profile) : null;
  const f = k => p?.fields?.[k];
  const apply = f("apply_url")?.value || p?.sources?.[0];
  const evidence = ["opens", "closes", "no_courses_allowed", "title"].map(k => f(k)).filter(x => x?.quote);
  return `
    <h2 id="e-name">${esc(e.name)}</h2>
    <p class="st st-${esc(e.status)}">${esc(STATUS[e.status])}${p?.opens ? "، " + esc(countdown(p.opens, p.closes, today())) : ""}</p>
    ${apply ? `<a class="primary" href="${esc(apply)}" target="_blank" rel="noopener">قدّم من الموقع الرسمي</a>` : ""}
    ${p ? `<button class="ghost" id="mark-applied" data-key="${esc(p.key)}">${applied.has(p.key) ? "ألغِ «قدّمت»" : "قدّمت"}</button>` : ""}
    ${m ? `<p class="match"><b>${m.pct}٪</b> ${m.reasons.map(esc).join("، ")}</p>` : ""}
    ${m?.warning ? `<p class="warn">${esc(m.warning)}</p>` : ""}
    ${p?.opens ? `<p>التسجيل من ${fmt(p.opens)}${p.closes ? " إلى " + fmt(p.closes) : ""}</p>` : ""}
    ${e.fulltime_history === "yes" ? `<p class="warn">اشترطت التفرّغ سابقاً: «${esc(e.fulltime_evidence)}»</p>` : ""}
    ${e.fulltime_history === "no" ? `<p class="good">ما اشترطت التفرّغ نصاً، فرصتك أعلى</p>` : ""}
    ${!p && e.expected_month ? `<p>المتوقع أن تفتح تقريباً في ${MONTHS[e.expected_month - 1]}</p>` : ""}
    ${!p && !e.expected_month ? `<p class="hint">موعد فتحها المعتاد غير معروف بعد.</p>` : ""}
    ${evidence.length ? `<h3>الدليل من المصدر</h3>${evidence.map(x => `<blockquote dir="auto">${esc(x.quote)}</blockquote>`).join("")}` : ""}
    ${p?.sources?.length ? `<p class="hint">المصادر: ${p.sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(new URL(u).hostname)}</a>`).join("، ")}</p>` : ""}
    <p class="hint">مصادر تُقرأ: ${e.sources_ok} من ${e.sources_total}${e.last_success ? "، آخر قراءة ناجحة " + fmt(e.last_success.slice(0, 10)) : ""}</p>`;
}

function openEntity(id) {
  const html = results && entityView(id);
  if (!html) return;
  $("#entity-body").innerHTML = html;
  $("#entity").showModal();
  history.replaceState(null, "", `#e=${encodeURIComponent(id)}`);
}
// التنبيه يفتح التطبيق على #e=الجهة مباشرة
function openFromHash() {
  const m = location.hash.match(/^#e=(.+)$/);
  if (m) openEntity(decodeURIComponent(m[1]));
}
addEventListener("hashchange", openFromHash);

document.addEventListener("click", ev => {
  const t = ev.target.closest("[data-entity]");
  if (t) return openEntity(t.dataset.entity);
  if (ev.target.id === "mark-applied") {
    const k = ev.target.dataset.key;
    applied.has(k) ? applied.delete(k) : applied.add(k);
    store.set("applied", [...applied]);
    ev.target.textContent = applied.has(k) ? "ألغِ «قدّمت»" : "قدّمت";
    render();
  }
});
document.addEventListener("keydown", ev => {
  if (ev.key === "Enter" && ev.target.matches?.(".card[data-entity]")) openEntity(ev.target.dataset.entity);
});
$("#entity").addEventListener("close", () => history.replaceState(null, "", location.pathname));
$("#search").addEventListener("input", () => results && render());

// الإعدادات
$("#open-settings").addEventListener("click", () => {
  const f = $("#settings-form");
  f.major.value = profile.major;
  f.hasCourses.checked = profile.hasCourses;
  f.minStars.value = String(profile.minStars);
  f.showJobs.checked = profile.showJobs;
  f.querySelectorAll('[name="interests"]').forEach(c => (c.checked = profile.interests.includes(c.value)));
  $("#settings").showModal();
});
$("#settings-form").addEventListener("submit", () => {
  const f = $("#settings-form");
  profile = { major: f.major.value.trim() || DEFAULT_PROFILE.major, hasCourses: f.hasCourses.checked,
              minStars: Number(f.minStars.value), showJobs: f.showJobs.checked, city: null,
              interests: [...f.querySelectorAll('[name="interests"]:checked')].map(c => c.value) };
  store.set("profile", profile);
  if (results) render();
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
load();

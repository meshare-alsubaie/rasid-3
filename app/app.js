// لوحة راصد الكاملة: طبقة فوق صفحة الكوكب، تعرض النتائج حسب ظروف المستخدم المحفوظة في جهازه.
import { DEFAULT_PROFILE, countdown, matchScore, rankPrograms } from "./core.js";
import { PUSH_URL, VAPID_PUBLIC } from "./config.js";

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

let hooks = { onOpen() {}, onClose() {} };

export function initBoard(res, h = {}) {
  results = res; hooks = { ...hooks, ...h }; render();
}

// فتح اللوحة يضيف خطوة في سجل المتصفح، فزر الرجوع في الجوال يقفلها ويرجعك للكوكب
export function openBoard({ entity = null, settings = false } = {}) {
  const board = $("#board");
  if (board.hidden) {
    board.hidden = false; document.documentElement.classList.add("board-open"); hooks.onOpen();
    history.pushState({ board: true }, "", "#board");
    requestAnimationFrame(() => board.classList.add("on"));
  }
  if (entity) openEntity(entity);
  if (settings) $("#open-settings").click();
}
function hideBoard() {
  const board = $("#board");
  if (board.hidden) return;
  board.classList.remove("on");
  document.documentElement.classList.remove("board-open"); hooks.onClose();
  setTimeout(() => { board.hidden = true; }, 350);
}
export function closeBoard() { history.state?.board ? history.back() : hideBoard(); }
addEventListener("popstate", () => { if (!history.state?.board) hideBoard(); });

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
}

document.addEventListener("click", ev => {
  const t = ev.target.closest("#board [data-entity]");
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
$("#close-board").addEventListener("click", closeBoard);
addEventListener("keydown", ev => { if (ev.key === "Escape" && !$("#board").hidden && !document.querySelector("dialog[open]")) closeBoard(); });
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

// ---------- التنبيهات المباشرة على هذا الجهاز ----------
// الجهاز يرسل عنوان تنبيه مجهولاً وحد النجوم فقط؛ لا اسم ولا تخصص ولا أي ظرف شخصي.
const pushStatus = msg => ($("#push-status").textContent = msg);
const b64ToBytes = s => { const p = "=".repeat((4 - (s.length % 4)) % 4); const r = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(r, c => c.charCodeAt(0)); };
async function registerPush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(VAPID_PUBLIC) });
  const r = await fetch(PUSH_URL + "/subscribe", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ subscription: sub.toJSON(), minStars: profile.minStars }) });
  if (!r.ok) throw new Error("subscribe " + r.status);
}
$("#enable-push").addEventListener("click", async () => {
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const installed = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (ios && !installed) return pushStatus("في الآيفون: أضف راصد للشاشة الرئيسية أولاً (زر المشاركة، ثم «إضافة إلى الشاشة الرئيسية»)، وافتحه من هناك واضغط هذا الزر.");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return pushStatus("هذا المتصفح لا يدعم التنبيهات. جرّب كروم أو سفاري الحديث.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return pushStatus("ما سمحت بالتنبيهات. تقدر تسمح لها من إعدادات المتصفح ثم تضغط الزر مرة ثانية.");
  try {
    await registerPush(); store.set("push", true);
    pushStatus("تم ✅ بتوصلك التنبيهات على هذا الجهاز للجهات من " + profile.minStars + " نجوم فأكثر.");
  } catch { pushStatus("تعذّر التفعيل الآن. تأكد من الإنترنت وجرّب بعد قليل."); }
});
// تغيير حد النجوم يحدّث الاشتراك نفسه
$("#settings-form").addEventListener("submit", () => { if (store.get("push", false)) registerPush().catch(() => {}); });
if (store.get("push", false)) pushStatus("التنبيهات مفعّلة على هذا الجهاز ✅");


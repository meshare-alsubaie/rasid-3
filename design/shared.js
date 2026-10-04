// الأجزاء المشتركة بين النماذج الثلاثة: الشريط، البطاقات، العدّ التنازلي، التلميح.
const D = window.RASID;
const TODAY = new Date(D.today + "T00:00:00");
const MONTHS = ["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"];
const KIND = { coop: "تدريب تعاوني", university: "تدريب جامعي", hint: "تلميح لبرنامج قادم" };
export const byId = Object.fromEntries(D.entities.map(e => [e.id, e]));
export const programsByEntity = Object.fromEntries(D.programs.map(p => [p.entity, p]));
export const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

function days(n) {
  if (n === 1) return "يوم واحد";
  if (n === 2) return "يومين";
  return n <= 10 ? `${n} أيام` : `${n} يوماً`;
}
function fmt(iso) { const d = new Date(iso + "T00:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; }
function diff(iso) { return Math.round((new Date(iso + "T00:00:00") - TODAY) / 86400000); }

export function status(p) {
  if (!p) return "none";
  if (p.closes && diff(p.closes) < 0) return "closed";
  if (p.opens && diff(p.opens) > 0) return "upcoming";
  if (p.closes && diff(p.closes) <= 3) return "soon";
  return p.opens || p.closes ? "open" : "listed";
}

function countdown(p) {
  if (p.opens && diff(p.opens) > 0) return { text: `يفتح بعد ${days(diff(p.opens))}`, cls: "" };
  if (p.closes) return { text: diff(p.closes) === 0 ? "آخر يوم اليوم" : `باقي ${days(diff(p.closes))}`, cls: "open" };
  return { text: "صفحة البرنامج متاحة", cls: "" };
}

export function renderChrome() {
  const live = D.programs.filter(p => status(p) !== "closed");
  document.body.insertAdjacentHTML("beforeend", `
    <div class="brand">راصد<small>التدريب التعاوني، من مصدره</small></div>
    <div class="news" role="status"><b>جديد منذ آخر زيارة:</b> أرامكو أعلنت التدريب الجامعي، والتسجيل ${fmt("2026-10-26")}</div>
    <section class="panel" aria-label="الفرص القادمة والمفتوحة">
      <h2>القادم والمفتوح</h2>
      ${live.map(p => {
        const e = byId[p.entity], c = countdown(p);
        return `<article class="card" data-entity="${e.id}">
          <div class="who">${e.name}</div>
          <div class="kind">${KIND[p.kind] || ""}${p.title ? "، " + p.title : ""}</div>
          <div class="count ${c.cls}">${c.text}</div>
          ${p.opens ? `<div class="dates">التسجيل من ${fmt(p.opens)} إلى ${fmt(p.closes)}</div>` : ""}
          ${p.no_courses ? `<span class="warn">تشترط التفرّغ: لا مواد أثناء التدريب</span>` : ""}
          <div><a class="apply" href="${p.apply}" target="_blank" rel="noopener">قدّم من الموقع الرسمي</a></div>
        </article>`;
      }).join("")}
    </section>
    <div class="tip" aria-hidden="true"></div>
    <div class="note">نموذج للتصميم ببيانات حقيقية. أشهر الفتح على الرسم تقريبية حتى يكتمل سجل السنوات.</div>`);
}

const tip = () => document.querySelector(".tip");
export function showTip(entity, x, y) {
  const t = tip(), p = programsByEntity[entity.id];
  const st = { open: "مفتوح الآن", upcoming: "أعلن وقريباً يفتح", soon: "يقفل قريباً", listed: "صفحة البرنامج متاحة" }[status(p)] || "لم يعلن بعد";
  t.innerHTML = `<b>${entity.name}</b>${"★".repeat(entity.stars)}${"☆".repeat(5 - entity.stars)}، ${st}`;
  t.style.left = Math.min(x + 14, innerWidth - t.offsetWidth - 10) + "px";
  t.style.top = (y + 14) + "px";
  t.classList.add("on");
}
export function hideTip() { tip().classList.remove("on"); }

// لون خفيف لكل جهة حسب طابعها (اللمسة الخفيفة)
export function tint(id) {
  if (["aramco", "sasref", "samref", "yasref", "satorp", "luberef", "sabic", "maaden"].includes(id)) return [0.37, 0.95, 0.78];
  if (["sdaia", "nca", "ncac", "site", "elm", "dga", "ncai", "ncdc"].includes(id)) return [0.62, 0.62, 1.0];
  return [0.56, 0.86, 1.0];
}

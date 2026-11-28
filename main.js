// المدخل: يحمّل النتائج مرة واحدة، ثم يشغّل صفحة الكوكب واللوحة معاً كتطبيق واحد.
import { isStale } from "./core.js";
import { initBoard, openBoard } from "./app.js";
import { initLanding } from "./landing.js";
import { loadOwnerFonts } from "./owner-fonts.js";

const banner = msg => { const b = document.getElementById("stale"); b.textContent = msg; b.hidden = false; };

async function start() {
  loadOwnerFonts();
  let results;
  try {
    results = await (await fetch("results.json", { cache: "no-cache" })).json();
  } catch {
    banner("تعذّر تحميل النتائج. تأكد من الإنترنت ثم افتح راصد مرة ثانية.");
    return;
  }
  if (isStale(results.generated_at)) banner("راصد ما تحدّث من أكثر من ١٢ ساعة. تابع مواقع الجهات بنفسك احتياطاً حتى يرجع.");
  let landing = null;
  initBoard(results, { onOpen: () => landing?.lenis?.stop(), onClose: () => landing?.lenis?.start() });
  landing = initLanding(results, () => openBoard());
  // روابط مباشرة: التنبيه يفتح #e=الجهة، و#board يفتح اللوحة
  const m = location.hash.match(/^#e=(.+)$/);
  if (m) openBoard({ entity: decodeURIComponent(m[1]) });
  else if (location.hash === "#board") { history.replaceState(null, "", location.pathname); openBoard(); }
  document.querySelectorAll("[data-settings]").forEach(a => a.addEventListener("click", () => openBoard({ settings: true })));
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
start();

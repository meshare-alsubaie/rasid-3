// خطوط ثمانية لأجهزة المالك فقط (رخصة ثمانية تمنع إتاحة ملفات الخط لغيره).
// الجهاز يُفعَّل مرة واحدة بفتح الرابط الخاص (#owner=الرمز)، فيُحفظ الرمز فيه، والخط يُجلب برمزه ويُخزَّن محلياً.
// أي جهاز آخر لا يملك الرمز: لا طلب أصلاً، ويبقى خط الموقع العادي.
import { PUSH_URL } from "./config.js";

const KEY = "rasid-owner";
const FACES = [
  ["Thmanyah Display", "thmanyahserifdisplay-Light", 300], ["Thmanyah Display", "thmanyahserifdisplay-Regular", 400],
  ["Thmanyah Sans", "thmanyahsans-Light", 300], ["Thmanyah Sans", "thmanyahsans-Regular", 400],
  ["Thmanyah Sans", "thmanyahsans-Medium", 500],
];

export async function loadOwnerFonts() {
  try {
    const m = location.hash.match(/^#owner=([\w-]{20,})$/);
    if (m) { localStorage.setItem(KEY, m[1]); history.replaceState(null, "", location.pathname); }
    const token = localStorage.getItem(KEY);
    if (!token) return;
    const cache = await caches.open("rasid-owner-fonts");
    await Promise.all(FACES.map(async ([family, file, weight]) => {
      const url = `${PUSH_URL}/font/${file}.woff2`;
      let res = await cache.match(url);
      if (!res) {
        res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
        if (!res.ok) throw new Error("font " + res.status);
        await cache.put(url, res.clone());
      }
      const face = new FontFace(family, await res.arrayBuffer(), { weight: String(weight), display: "swap" });
      document.fonts.add(await face.load());
    }));
    document.documentElement.classList.add("owner-fonts");
  } catch { /* بدون الخط الخاص: يبقى خط الموقع العادي */ }
}

// إذا فُتح الرابط الخاص والصفحة مفتوحة أصلاً، نعيد التحميل حتى يُطبَّق
addEventListener("hashchange", () => { if (/^#owner=/.test(location.hash)) location.reload(); });

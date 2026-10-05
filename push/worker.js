// خادم اشتراكات التنبيهات (عامل كلاودفلير): يحفظ عناوين الأجهزة المجهولة وحد النجوم فقط.
// الإرسال نفسه من المحرّك على غيت هاب. لا أسماء ولا أرقام ولا تخصصات هنا أبداً.

const ALLOWED_ORIGINS = ["https://meshare-alsubaie.github.io", "http://localhost:8766", "http://localhost:8767"];
const MAX_BODY = 4000;

function cors(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { "access-control-allow-origin": allow, "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
           "access-control-allow-headers": "content-type,authorization", "vary": "origin" };
}
const json = (data, status, headers) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...headers } });

async function idOf(endpoint) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return [...new Uint8Array(d)].slice(0, 16).map(b => b.toString(16).padStart(2, "0")).join("");
}
function validSub(s) {
  return s && typeof s.endpoint === "string" && s.endpoint.startsWith("https://") && s.endpoint.length < 1000
    && s.keys && typeof s.keys.p256dh === "string" && typeof s.keys.auth === "string";
}
async function body(req) {
  const t = await req.text();
  if (t.length > MAX_BODY) throw new Error("كبير");
  return JSON.parse(t || "{}");
}
const authorized = (req, env) => env.SEND_TOKEN && req.headers.get("authorization") === `Bearer ${env.SEND_TOKEN}`;

export default {
  async fetch(req, env) {
    const h = cors(req.headers.get("origin") || "");
    const { pathname } = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    try {
      if (req.method === "POST" && pathname === "/subscribe") {
        const b = await body(req);
        if (!validSub(b.subscription)) return json({ error: "اشتراك غير صالح" }, 400, h);
        const minStars = Math.min(5, Math.max(1, Number(b.minStars) || 3));
        const id = await idOf(b.subscription.endpoint);
        await env.SUBS.put(id, JSON.stringify({ subscription: b.subscription, minStars, at: Date.now() }));
        return json({ ok: true, id }, 200, h);
      }
      if (req.method === "POST" && pathname === "/unsubscribe") {
        const b = await body(req);
        if (typeof b.endpoint === "string") await env.SUBS.delete(await idOf(b.endpoint));
        return json({ ok: true }, 200, h);
      }
      if (req.method === "GET" && pathname === "/subs") {
        if (!authorized(req, env)) return json({ error: "غير مصرّح" }, 401, h);
        const out = [];
        let cursor;
        do {
          const page = await env.SUBS.list({ cursor });
          for (const k of page.keys) {
            const v = await env.SUBS.get(k.name);
            if (v) out.push({ id: k.name, ...JSON.parse(v) });
          }
          cursor = page.list_complete ? null : page.cursor;
        } while (cursor);
        return json(out, 200, h);
      }
      // خط ثمانية لأجهزة المالك فقط: برمزه، وبلا تخزين في وسطاء عامين
      if (req.method === "GET" && pathname.startsWith("/font/")) {
        const name = pathname.slice(6);
        if (!/^[a-z-]+\.woff2$/i.test(name)) return json({ error: "غير موجود" }, 404, h);
        if (!env.OWNER_TOKEN || req.headers.get("authorization") !== `Bearer ${env.OWNER_TOKEN}`) return json({ error: "غير مصرّح" }, 401, h);
        const data = await env.FONTS.get(name, "arrayBuffer");
        if (!data) return json({ error: "غير موجود" }, 404, h);
        return new Response(data, { status: 200, headers: { ...h, "content-type": "font/woff2", "cache-control": "private, max-age=31536000" } });
      }
      if (req.method === "DELETE" && pathname.startsWith("/subs/")) {
        if (!authorized(req, env)) return json({ error: "غير مصرّح" }, 401, h);
        await env.SUBS.delete(pathname.slice(6));
        return json({ ok: true }, 200, h);
      }
      return json({ error: "غير موجود" }, 404, h);
    } catch {
      return json({ error: "طلب غير صالح" }, 400, h);
    }
  },
};

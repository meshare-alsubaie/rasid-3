// اختبارات خادم الاشتراكات: node --test "push/*.test.js"
import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

function fakeKV() {
  const m = new Map();
  return { m,
    put: async (k, v) => void m.set(k, v), get: async k => m.get(k) ?? null, delete: async k => void m.delete(k),
    list: async () => ({ keys: [...m.keys()].map(name => ({ name })), list_complete: true }) };
}
const env = () => ({ SUBS: fakeKV(), SEND_TOKEN: "secret-token" });
const ORIGIN = "https://meshare-alsubaie.github.io";
const SUB = { endpoint: "https://fcm.googleapis.com/fcm/send/abc", keys: { p256dh: "x", auth: "y" } };
const req = (method, path, body, headers = {}) => new Request("https://push.example" + path, {
  method, headers: { "content-type": "application/json", origin: ORIGIN, ...headers }, body: body ? JSON.stringify(body) : undefined });

test("اشتراك جهاز يُحفظ مع حد النجوم، ويرجع معرّفاً", async () => {
  const e = env();
  const r = await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 3 }), e);
  assert.equal(r.status, 200);
  const { id } = await r.json();
  assert.equal(JSON.parse(e.SUBS.m.get(id)).minStars, 3);
  assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN);
});

test("نفس الجهاز مرتين = اشتراك واحد (يتحدّث)", async () => {
  const e = env();
  await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 3 }), e);
  await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 5 }), e);
  assert.equal(e.SUBS.m.size, 1);
  assert.equal(JSON.parse([...e.SUBS.m.values()][0]).minStars, 5);
});

test("يرفض اشتراكاً غير صالح", async () => {
  const e = env();
  for (const bad of [{}, { subscription: { endpoint: "http://insecure/x", keys: {} } }, { subscription: { endpoint: "https://a/b" } }]) {
    const r = await worker.fetch(req("POST", "/subscribe", bad), e);
    assert.equal(r.status, 400);
  }
  assert.equal(e.SUBS.m.size, 0);
});

test("قائمة الاشتراكات للمحرّك فقط برمز سري", async () => {
  const e = env();
  await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 2 }), e);
  assert.equal((await worker.fetch(req("GET", "/subs"), e)).status, 401);
  assert.equal((await worker.fetch(req("GET", "/subs", null, { authorization: "Bearer wrong" }), e)).status, 401);
  const r = await worker.fetch(req("GET", "/subs", null, { authorization: "Bearer secret-token" }), e);
  const list = await r.json();
  assert.equal(list.length, 1); assert.equal(list[0].subscription.endpoint, SUB.endpoint);
});

test("المحرّك يحذف اشتراكاً ميتاً برمزه فقط", async () => {
  const e = env();
  const { id } = await (await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 2 }), e)).json();
  assert.equal((await worker.fetch(req("DELETE", "/subs/" + id), e)).status, 401);
  assert.equal((await worker.fetch(req("DELETE", "/subs/" + id, null, { authorization: "Bearer secret-token" }), e)).status, 200);
  assert.equal(e.SUBS.m.size, 0);
});

test("إلغاء الاشتراك من الجهاز نفسه", async () => {
  const e = env();
  await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 2 }), e);
  await worker.fetch(req("POST", "/unsubscribe", { endpoint: SUB.endpoint }), e);
  assert.equal(e.SUBS.m.size, 0);
});

test("طلب من موقع غريب لا يأخذ إذن المتصفح", async () => {
  const r = await worker.fetch(req("POST", "/subscribe", { subscription: SUB, minStars: 2 }, { origin: "https://evil.example" }), env());
  assert.notEqual(r.headers.get("access-control-allow-origin"), "https://evil.example");
});

test("طلبات الاستئذان المسبق (OPTIONS) تنجح", async () => {
  const r = await worker.fetch(req("OPTIONS", "/subscribe"), env());
  assert.equal(r.status, 204);
});

// ---------- خط المالك ----------
const fontEnv = () => ({ ...env(), OWNER_TOKEN: "owner-secret", FONTS: { get: async (k, t) => k === "thmanyahsans-Light.woff2" ? new Uint8Array([1, 2, 3]).buffer : null } });

test("الخط لا يُعطى بدون رمز المالك", async () => {
  assert.equal((await worker.fetch(req("GET", "/font/thmanyahsans-Light.woff2"), fontEnv())).status, 401);
  assert.equal((await worker.fetch(req("GET", "/font/thmanyahsans-Light.woff2", null, { authorization: "Bearer wrong" }), fontEnv())).status, 401);
});

test("الخط يُعطى برمز المالك ولا يُخزَّن في وسيط عام", async () => {
  const r = await worker.fetch(req("GET", "/font/thmanyahsans-Light.woff2", null, { authorization: "Bearer owner-secret" }), fontEnv());
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("content-type"), "font/woff2");
  assert.match(r.headers.get("cache-control"), /private/);
});

test("أسماء ملفات غريبة ترفض", async () => {
  const r = await worker.fetch(req("GET", "/font/..%2Fsecret", null, { authorization: "Bearer owner-secret" }), fontEnv());
  assert.equal(r.status, 404);
});

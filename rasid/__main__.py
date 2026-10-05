"""تشغيل جولة واحدة حقيقية: uv run python -m rasid

متغيرات البيئة (في غيت هاب تأتي من الخزنة السرية، ومحلياً من secrets.local.env):
  GEMINI_API_KEY, GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TG_GROUP_CHAT, TG_OWNER_CHAT, HC_PING_URL (اختياري)
  RASID_TEST_MODE=1   كل رسائل القروب تذهب لمحادثة المؤسس الخاصة بعلامة تجربة
  RASID_LIMIT=N       أول N جهة فقط (للتجربة المحلية)
"""
from __future__ import annotations

import json
import os
import sys
import time
from functools import partial
from pathlib import Path

import httpx

from rasid.classify.chain import Budget, classify
from rasid.classify.providers import call_provider, load_providers
from rasid.dates import riyadh_now
from rasid.entities import load_entities_safe
from rasid.fetch import fetch, set_inbox
from rasid.notify.telegram import send
from rasid.notify.webpush import PushConfig, send_push
from rasid.publish import build_results
from rasid.run import Deps, State, run_once, saudi_list

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    local = ROOT / "secrets.local.env"
    if local.exists():
        for line in local.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if v})
    return env


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    env = load_env()
    now = riyadh_now()
    STATE_DIR.mkdir(exist_ok=True)
    state_path = STATE_DIR / "state.json"
    st = State.load(state_path)
    inbox_path = STATE_DIR / "inbox.json"
    if inbox_path.exists():
        set_inbox(json.loads(inbox_path.read_text(encoding="utf-8")))

    last_good = STATE_DIR / "entities.last_good.yaml"
    if not last_good.exists():
        last_good.write_text((ROOT / "config/entities.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    entities, ent_err = load_entities_safe(ROOT / "config/entities.yaml", last_good)
    if ent_err:
        st.outbox.enqueue(f"entities-error:{now.date()}", "owner",
                          f"⚠️ ملف الجهات فيه خطأ، والمحرّك يكمل بآخر نسخة سليمة.\n{ent_err}", now, urgent=True)
    if env.get("RASID_LIMIT"):
        entities = entities[: int(env["RASID_LIMIT"])]

    providers = load_providers(ROOT / "config/providers.yaml")
    budget = Budget.from_dict(st.meta.get("budget", {}), today=now.date())
    client = httpx.Client()
    test_mode = env.get("RASID_TEST_MODE") == "1"
    chats = {"owner": env.get("TG_OWNER_CHAT", ""),
             "group": env.get("TG_OWNER_CHAT" if test_mode else "TG_GROUP_CHAT", "")}

    push_cfg = PushConfig(env.get("PUSH_URL", ""), env.get("PUSH_SEND_TOKEN", ""), env.get("VAPID_PRIVATE", ""))

    def sender(chat: str, text: str) -> int:
        if chat == "push":  # التنبيه المباشر لأجهزة التطبيق؛ قبل تشغيل خادم الاشتراكات لا أجهزة أصلاً
            return send_push(push_cfg, text, client) if push_cfg.base else 0
        if test_mode and chat == "group":
            text = "🧪 وضع تجربة (كانت ستذهب للقروب):\n\n" + text
        return send(env.get("TELEGRAM_BOT_TOKEN", ""), chats[chat], text, client).message_id

    deps = Deps(fetch=partial(fetch, client=client),
                classify=lambda text: classify(text, providers, budget,
                                               lambda p, s, u: call_provider(p, s, u, env, client)),
                send=sender)
    started = time.monotonic()
    budget_min = float(env.get("RASID_BUDGET_MIN", "100"))  # أقل من حد الجولة (١٥٠ دقيقة) بهامش للحفظ والنشر
    rep = run_once(now, entities, st, deps,
                   deadline=lambda: time.monotonic() - started > budget_min * 60,
                   checkpoint=lambda: (st.meta.__setitem__("budget", budget.to_dict()), st.save(state_path)))
    st.meta["budget"] = budget.to_dict()
    st.save(state_path)
    (STATE_DIR / "results.json").write_text(json.dumps(build_results(st, entities, now), ensure_ascii=False),
                                            encoding="utf-8")
    (STATE_DIR / "saudi_list.json").write_text(json.dumps(saudi_list(st), ensure_ascii=False, indent=0),
                                               encoding="utf-8")

    print(f"[راصد] {now:%Y-%m-%d %H:%M} | مصادر سليمة {rep.fetch_ok} | فاشلة {rep.fetch_fail} | "
          f"جديد {rep.new_items} | أحكام {rep.verdicts} | معلّق {rep.pending} | أُرسل {rep.sent} | "
          f"طابور {len(st.queue.items)} | مؤجل للجولة التالية {rep.deferred}")
    if env.get("HC_PING_URL"):
        try:
            client.post(env["HC_PING_URL"], content=f"ok {rep.fetch_ok}/{rep.fetch_ok + rep.fetch_fail}", timeout=15)
        except httpx.HTTPError as e:
            print(f"[الحارس] تعذّر إرسال النبضة: {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

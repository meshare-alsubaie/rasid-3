"""الإطلاق للقروب: رسالة بكل المفتوح والقادم، ثم إيقاف وضع التجربة.

  uv run python scripts/go_live.py --preview   يرسل رسالة الإطلاق لمحادثة المالك فقط ليراها
  uv run python scripts/go_live.py --go        يرسلها للقروب ويوقف وضع التجربة (قرار المالك)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rasid.__main__ import load_env  # noqa: E402
from rasid.dates import riyadh_now  # noqa: E402
from rasid.entities import load_entities  # noqa: E402
from rasid.notify.telegram import send  # noqa: E402
from rasid.notify.templates import launch_message  # noqa: E402
from rasid.programs import Programs  # noqa: E402

REPO = "meshare-alsubaie/rasid-3"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "--preview"
    raw = subprocess.run(["git", "show", "origin/state:state.json"], cwd=ROOT, capture_output=True)
    if raw.returncode != 0:
        subprocess.run(["git", "fetch", "-q", "origin", "state"], cwd=ROOT)
        raw = subprocess.run(["git", "show", "origin/state:state.json"], cwd=ROOT, capture_output=True)
    programs = Programs.from_dict(json.loads(raw.stdout.decode("utf-8"))["programs"])
    names = {e.id: e.name_ar for e in load_entities(ROOT / "config/entities.yaml")}
    text = launch_message(list(programs.items.values()), names, riyadh_now().date())
    env = load_env()
    chat = env["TG_GROUP_CHAT"] if mode == "--go" else env["TG_OWNER_CHAT"]
    if mode != "--go":
        text = "🧪 معاينة رسالة الإطلاق (لم تُرسل للقروب):\n\n" + text
    receipt = send(env["TELEGRAM_BOT_TOKEN"], chat, text, httpx.Client())
    print(f"أُرسلت (إيصال {receipt.message_id})")
    if mode == "--go":
        subprocess.run(["gh", "variable", "set", "RASID_TEST_MODE", "--body", "0", "-R", REPO], check=True)
        print("وضع التجربة متوقف: التنبيهات تذهب للقروب من الجولة القادمة.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

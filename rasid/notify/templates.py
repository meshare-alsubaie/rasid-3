"""قوالب الرسائل: نصوص عربية ثابتة مكتوبة مسبقاً، والبيانات تعبّئ الخانات فقط."""
from __future__ import annotations

from datetime import date

from hijridate import Gregorian

from rasid.programs import Change, Program

GREG_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
               "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
KIND_AR = {"coop": "تدريب تعاوني", "university": "تدريب جامعي", "hint": "تلميح لبرنامج قادم",
           "grad_program": "برنامج لحديثي التخرج", "job": "وظيفة"}
FIELD_AR = {"opens": "تاريخ الفتح", "closes": "تاريخ الإغلاق"}


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    h = Gregorian(d.year, d.month, d.day).to_hijri()
    return f"{d.day} {GREG_MONTHS[d.month - 1]} {d.year} ({h.day} {h.month_name('ar')} {h.year}هـ)"


def _val(p: Program, name: str):
    return (p.fields.get(name) or {}).get("value")


def _quote(p: Program, name: str) -> str | None:
    return (p.fields.get(name) or {}).get("quote")


def render(change: Change, p: Program, entity_name: str) -> str:
    if change.kind == "important_update":
        detail = change.detail_ar
        for en, ar in FIELD_AR.items():
            detail = detail.replace(en, ar)
        lines = [f"✏️ تحديث مهم: {entity_name}", detail]
    elif change.kind == "hint" or p.kind == "hint":
        lines = [f"💡 تلميح غير مؤكّد: {entity_name}",
                 "لمّحت الجهة لبرنامج طلابي قادم، والتفاصيل ما نزلت. بنرسل لكم أول ما ينزل الإعلان الرسمي."]
    else:
        lines = [f"🟢 {KIND_AR.get(p.kind, 'فرصة')} جديد: {entity_name}"]
        if _val(p, "title"):
            lines.append(str(_val(p, "title")))
    if p.kind == "university":
        lines.append("ℹ️ تدريب جامعي، تأكّد من جامعتك هل يُحتسب تعاونياً.")
    if p.uncertain:
        lines.append("⚠️ غير مؤكّد: رُصد بالكلمات لأن الذكاء متوقف مؤقتاً، وبيتأكد لاحقاً.")
    opens, closes = _val(p, "opens"), _val(p, "closes")
    if opens:
        lines.append(f"📅 يفتح: {fmt_date(opens)}")
    if closes:
        lines.append(f"⏳ يقفل: {fmt_date(closes)}")
    if _val(p, "no_courses_allowed") is True:
        lines.append("🔴 تشترط التفرّغ: لا يُسمح بتسجيل مواد أثناء التدريب.")
    if _val(p, "apply_url"):
        lines.append(f"🔗 التقديم الرسمي: {_val(p, 'apply_url')}")
    evidence = _quote(p, "opens") or _quote(p, "closes") or (p.fields.get("title") or {}).get("quote")
    if evidence:
        lines.append(f"📌 الدليل: «{evidence}»")
    if p.sources:
        lines.append(f"المصدر: {p.sources[0]}")
    return "\n".join(lines)


def reminders(programs: list[Program], today: date, names: dict[str, str]) -> list[tuple[str, str]]:
    """تذكيران فقط لكل برنامج: قبل الإغلاق بـ٣ أيام وقبله بيوم. المعرّف يمنع التكرار في الصندوق."""
    out: list[tuple[str, str]] = []
    for p in programs:
        closes = _val(p, "closes")
        if p.family != "student" or not closes:
            continue
        left = (date.fromisoformat(closes) - today).days
        if 1 < left <= 3:
            tag, txt = "rem3", f"باقي {left} أيام"
        elif 0 <= left <= 1:
            tag, txt = "rem1", "آخر يوم" if left == 0 else "باقي يوم واحد"
        else:
            continue
        name = names.get(p.entity_id, p.entity_id)
        msg = f"⏰ {txt} على إغلاق {name}\nيقفل: {fmt_date(closes)}"
        if _val(p, "apply_url"):
            msg += f"\n🔗 التقديم الرسمي: {_val(p, 'apply_url')}"
        out.append((f"{tag}:{p.key}", msg))
    return out

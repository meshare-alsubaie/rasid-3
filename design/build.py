"""يدمج كل نموذج في ملف واحد مستقل يفتح بالنقر المزدوج (بلا خادم)."""
import re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "dist"
OUT.mkdir(exist_ok=True)
css = (HERE / "shared.css").read_text(encoding="utf-8")
data = (HERE / "data.js").read_text(encoding="utf-8")
shared = (HERE / "shared.js").read_text(encoding="utf-8")
names = re.findall(r"^export (?:const|function) (\w+)", shared, re.M)
shared_iife = "const {%s} = (() => {\n%s\nreturn {%s};\n})();" % (
    ", ".join(names), shared.replace("export ", ""), ", ".join(names))
for page in ["a-observatory.html", "b-orbit.html", "c-constellation.html"]:
    html = (HERE / page).read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="shared.css">', f"<style>{css}</style>")
    html = html.replace('<script src="data.js"></script>', f"<script>{data}</script>")
    html = re.sub(r'import \{[^}]*\} from "\./shared\.js";', lambda m: shared_iife, html)
    (OUT / page).write_text(html, encoding="utf-8")
    print("built", page, len(html))

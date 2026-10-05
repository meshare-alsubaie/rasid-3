"""يدمج المرصد ٢ في ملف واحد مستقل يفتح بالنقر المزدوج (البيانات ومنطق التطبيق داخله)."""
import re
from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "index.html").read_text(encoding="utf-8")
data = (HERE / "data.js").read_text(encoding="utf-8")
core = (HERE.parent.parent / "app" / "core.js").read_text(encoding="utf-8")
names = re.findall(r"^export (?:const|function) (\w+)", core, re.M)
core_iife = "const {%s} = (() => {\n%s\nreturn {%s};\n})();" % (", ".join(names), core.replace("export ", ""), ", ".join(names))
html = html.replace('<script src="data.js"></script>', f"<script>{data}</script>")
html = re.sub(r'import \{[^}]*\} from "\.\./\.\./app/core\.js";', lambda m: core_iife, html)
(HERE / "dist.html").write_text(html, encoding="utf-8")
print("built", len(html))

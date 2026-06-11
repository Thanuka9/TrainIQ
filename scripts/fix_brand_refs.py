"""Fix remaining brand references in standalone templates."""
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1] / "templates"
for p in root.rglob("*.html"):
    if "macros" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")
    new = text.replace("{{ global_org_name[0]|upper }}", "{{ org_initial }}")
    new = new.replace("{{ global_org_name }}", "{{ display_org_name }}")
    new = new.replace("{% block title %}{{ display_org_name }}{% endblock %}", "{% block title %}{{ display_org_name }}{% endblock %}")
    if new != text:
        p.write_text(new, encoding="utf-8")
        print("fixed", p.relative_to(root))

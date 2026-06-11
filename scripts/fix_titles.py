"""One-off: replace hardcoded TrainIQ in template block titles."""
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1] / "templates"
pat = re.compile(r" — TrainIQ(\{%\s*endblock\s*%\})")
for p in root.rglob("*.html"):
    text = p.read_text(encoding="utf-8")
    new = pat.sub(r" — {{ display_org_name }}\1", text)
    if new != text:
        p.write_text(new, encoding="utf-8")
        print("updated", p.relative_to(root))

# Standalone title tags
pat2 = re.compile(r"(<title>[^<]+) — TrainIQ(</title>)")
for p in root.rglob("*.html"):
    text = p.read_text(encoding="utf-8")
    new = pat2.sub(r"\1 — {{ display_org_name }}\2", text)
    if new != text:
        p.write_text(new, encoding="utf-8")
        print("title", p.relative_to(root))

# global_org_name == 'TrainIQ' -> is_platform_brand
for p in root.rglob("*.html"):
    text = p.read_text(encoding="utf-8")
    new = text.replace("global_org_name == 'TrainIQ'", "is_platform_brand")
    if new != text:
        p.write_text(new, encoding="utf-8")
        print("brand flag", p.relative_to(root))

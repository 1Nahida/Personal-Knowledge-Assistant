
import sys
from docx import Document
d = Document(r"<桌面>\基于本地知识库的知识问答助手 PRD 开发文档 v2.docx")
out = []
for p in d.paragraphs:
    t = p.text
    if t.strip():
        style = p.style.name if p.style else ""
        prefix = ""
        if "Heading" in style:
            lvl = style.replace("Heading", "").strip()
            prefix = "#" * int(lvl or 1) + " "
        out.append(prefix + t)
for i, tbl in enumerate(d.tables):
    out.append(f"[TABLE {i+1}]")
    for row in tbl.rows:
        cells = [c.text.replace(chr(10), " | ") for c in row.cells]
        out.append(" || ".join(cells))
text = chr(10).join(out)
with open(r"<项目根>\docs\_prd_extracted.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("PARAGRAPHS:", len(d.paragraphs))
print("TABLES:", len(d.tables))
print("CHARS:", len(text))

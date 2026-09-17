#!/usr/bin/env python3
"""Render the Thai OpenFOAM/blastFoam manual to a searchable A4 PDF.

Dependencies: markdown, weasyprint and pymupdf. A vendored OFL Noto Sans Thai
font keeps Thai shaping independent of system fonts. A second invisible text
layer preserves exact Thai Unicode for PDF readers whose shaping extraction
does not correctly reconstruct the Thai sara-am character.
"""

from pathlib import Path
import re
import textwrap
import markdown
import pymupdf
from weasyprint import HTML


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "คู่มือ_OpenFOAM9_blastFoam_ฉบับระบบ.md"
OUTPUT = ROOT / "คู่มือ_OpenFOAM9_blastFoam_ฉบับระบบ.pdf"

body = markdown.markdown(
    SOURCE.read_text(encoding="utf-8"),
    extensions=["toc", "tables", "fenced_code", "sane_lists"],
    extension_configs={"toc": {"toc_depth": "2-3", "title": "สารบัญ"}},
)

html = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>คู่มือการตั้งค่า OpenFOAM 9 และ blastFoam แบบครบวงจร</title>
<meta name="author" content="คู่มือสำหรับระบบ OpenFOAM/blastFoam ในเครื่องนี้">
<style>
@font-face {{
  font-family: NotoThai;
  src: url('assets/NotoSansThai.ttf');
  font-weight: 100 900;
}}
@page {{
  size: A4;
  margin: 17mm 17mm 19mm 17mm;
  @bottom-left {{ content: 'OpenFOAM 9 · blastFoam · 15 ก.ย. 2026'; font: 8pt NotoThai; color: #607283; }}
  @bottom-right {{ content: counter(page) ' / ' counter(pages); font: 8pt NotoThai; color: #607283; }}
}}
html {{ font-family: NotoThai, sans-serif; font-size: 9.5pt; line-height: 1.58; color: #233244; }}
body {{ margin: 0; }}
h1 {{ color: #14334c; font-size: 23pt; line-height: 1.28; border-bottom: 3pt solid #ea8b33; padding-bottom: 7mm; margin: 7mm 0 5mm; }}
h2 {{ color: #16445d; font-size: 14pt; line-height: 1.3; border-bottom: 0.6pt solid #c7d6df; padding-bottom: 2mm; margin: 9mm 0 3mm; break-after: avoid; }}
h3 {{ color: #9b5018; font-size: 10.5pt; line-height: 1.35; margin: 6mm 0 2mm; break-after: avoid; }}
p {{ margin: 0 0 3.1mm; text-align: left; }}
blockquote {{ margin: 3mm 0 4mm; padding: 2.5mm 3mm; border-left: 2.5pt solid #e5a05e; background: #fff8ed; break-inside: avoid; }}
blockquote p {{ margin: 0; }}
code {{ font-family: 'DejaVu Sans Mono', monospace; font-size: 7.5pt; background: #f1f4f5; padding: 0.3mm 0.5mm; overflow-wrap: anywhere; }}
pre {{ font-family: 'DejaVu Sans Mono', monospace; font-size: 7.1pt; line-height: 1.4; color: #192d3d; background: #f1f4f5; padding: 2.5mm 3mm; border-left: 1.5pt solid #92aaba; white-space: pre-wrap; overflow-wrap: anywhere; margin: 3mm 0 4mm; }}
pre code {{ font: inherit; background: transparent; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 3mm 0 5mm; table-layout: fixed; font-size: 8.1pt; }}
th {{ text-align: left; color: #fff; background: #28536c; }}
td, th {{ border: 0.4pt solid #c9d5dc; padding: 1.4mm 1.7mm; vertical-align: top; overflow-wrap: anywhere; }}
tr:nth-child(even) td {{ background: #f7fafb; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; }}
ul, ol {{ padding-left: 6mm; margin: 2mm 0 4mm; }}
li {{ margin: 1.4mm 0; }}
a {{ color: #0b638d; text-decoration: none; overflow-wrap: anywhere; }}
.toc {{ background: #eff6f8; border: 0.6pt solid #c9dbe3; border-radius: 2mm; padding: 4mm 5mm; margin: 5mm 0 8mm; }}
.toc > span {{ display: block; font-size: 12pt; font-weight: 700; color: #143b54; margin-bottom: 2mm; }}
.toc ul {{ margin: 0; padding-left: 6mm; }}
.toc li {{ margin: 0.7mm 0; font-size: 8.6pt; }}
</style>
</head>
<body>{body}</body>
</html>"""

HTML(string=html, base_url=str(ROOT)).write_pdf(str(OUTPUT))

# WeasyPrint renders Thai correctly, but PDF text extraction can map the
# sara-am glyph to a semicolon. Add source text invisibly at the section's
# bookmarked page so native PDF search can find the exact Unicode spelling.
document = pymupdf.open(OUTPUT)
page_by_title = {title: page - 1 for _, title, page in document.get_toc()}
source_sections = []
heading = "คู่มือการตั้งค่า OpenFOAM 9 และ blastFoam แบบครบวงจร"
lines = []
for line in SOURCE.read_text(encoding="utf-8").splitlines():
    if line.startswith("## ") or line.startswith("### Prompt "):
        source_sections.append((heading, lines))
        heading = re.sub(r"[`*_]", "", line.lstrip("# "))
        lines = []
    else:
        lines.append(line)
source_sections.append((heading, lines))

page_text = {i: [] for i in range(len(document))}
for title, section_lines in source_sections:
    if title in page_by_title:
        page_text[page_by_title[title]].extend(section_lines)

for page_index, section_lines in page_text.items():
    if not section_lines:
        continue
    page = document[page_index]
    page.insert_font(fontname="NotoThaiSearch", fontfile=str(ROOT / "assets/NotoSansThai.ttf"))
    y = 30.0
    for source_line in section_lines:
        plain = re.sub(r"[`*_>#]", "", source_line).strip()
        if not plain or plain == "[TOC]":
            continue
        for short_line in textwrap.wrap(plain, width=92, break_long_words=True):
            page.insert_text(
                (49, y), short_line, fontname="NotoThaiSearch",
                fontsize=2.3, render_mode=3,
            )
            y += 3.2

searchable = OUTPUT.with_name(OUTPUT.stem + ".searchable.pdf")
document.save(searchable, garbage=4, deflate=True)
document.close()
searchable.replace(OUTPUT)
print(OUTPUT)

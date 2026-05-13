#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pypdf>=5.0",
#   "reportlab>=4.0",
# ]
# ///
"""Export an annotated PDF for sharing.

Reads PDFs/{citekey}.pdf + Annotations/{citekey}.json + PaperNotes/{citekey}.md
and produces a derivative PDF with:

  1. The original pages, with a small numbered badge stamped next to
     each user annotation's bounding rect (top-right corner).
  2. Appendix pages at the end:
       - The .md note rendered as paragraphs.
       - A numbered list mirroring the badges: number, page, kind,
         excerpt (highlights only), and comment.

Mirrors the in-app right-pane annotation list, so a reader can scan
the PDF for the markers and flip to the back for the full feedback.

Coordinate convention: the EmbedPDF sidecar stores rects in top-left-
origin page coordinates (matches the SVG / on-screen layout). PDF
native is bottom-left-origin, so we convert via
`pdf_y = page_height - sidecar_y`.

Input: --citekey CITEKEY [--out PATH]
Output (stdout): JSON `{output, annotations}`.
"""

import argparse
import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

VAULT_ROOT = Path(
    os.environ.get("LITERATURE_VAULT")
    or Path(__file__).absolute().parent.parent
)

# PdfAnnotationSubtype values from @embedpdf/models — matched in
# viewer/src/panes/NoteEditor.svelte. Keep in sync if EmbedPDF ever
# remaps these.
SUBTYPE_TEXT = 1
SUBTYPE_FREETEXT = 3
SUBTYPE_SQUARE = 4
SUBTYPE_CIRCLE = 5
SUBTYPE_LINE = 6
SUBTYPE_HIGHLIGHT = 9
SUBTYPE_INK = 14

ACCENT_HEX = "#7a3a14"  # matches --accent in the viewer
INK_HEX = "#1a1612"


def kind_label(subtype: int, custom: dict | None) -> str:
    if subtype == SUBTYPE_TEXT and custom and custom.get("bookmark"):
        return "bookmark"
    return {
        SUBTYPE_TEXT: "sticky",
        SUBTYPE_FREETEXT: "free text",
        SUBTYPE_HIGHLIGHT: "highlight",
        SUBTYPE_SQUARE: "rectangle",
        SUBTYPE_CIRCLE: "ellipse",
        SUBTYPE_LINE: "line",
        SUBTYPE_INK: "drawing",
    }.get(subtype, "annotation")


def load_user_annotations(sidecar_path: Path) -> list[dict]:
    """Read the sidecar JSON and normalise each entry to the shape the
    appendix builder + overlay builder both consume."""
    with sidecar_path.open() as f:
        items = json.load(f)
    out: list[dict] = []
    for it in items:
        a = it.get("annotation", {})
        rect = a.get("rect")
        if not rect or "origin" not in rect or "size" not in rect:
            continue
        subtype = a.get("type")
        custom = a.get("custom") or {}
        kind = kind_label(subtype, custom)
        contents = a.get("contents") or ""
        excerpt = contents if kind == "highlight" else ""
        comment = (
            contents
            if kind in ("sticky", "free text")
            else custom.get("comment") or ""
        )
        out.append({
            "id": a.get("id", ""),
            "page": a.get("pageIndex", 0),
            "rect": rect,
            "kind": kind,
            "subtype": subtype,
            "color": a.get("strokeColor") or a.get("color"),
            "excerpt": excerpt,
            "comment": comment,
        })
    # Sort: by page, then top-down within each page (sidecar y is
    # top-origin so ascending y = visually higher).
    out.sort(key=lambda x: (x["page"], x["rect"]["origin"]["y"], x["rect"]["origin"]["x"]))
    for i, ann in enumerate(out):
        ann["number"] = i + 1
    return out


def build_badge_overlays(
    annotations: list[dict], reader: PdfReader
) -> dict[int, "object"]:
    """Build a one-page overlay PDF for each page that has annotations,
    drawing a numbered accent-coloured circle near each annotation."""
    by_page: dict[int, list[dict]] = {}
    for ann in annotations:
        by_page.setdefault(ann["page"], []).append(ann)

    overlays: dict[int, object] = {}
    for page_idx, anns in by_page.items():
        if page_idx >= len(reader.pages):
            continue
        page = reader.pages[page_idx]
        mb = page.mediabox
        w = float(mb.width)
        h = float(mb.height)
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        for ann in anns:
            origin = ann["rect"]["origin"]
            size = ann["rect"]["size"]
            # Place badge at top-right corner of the annotation's rect
            # in PDF coordinates (bottom-left origin).
            badge_r = 8.0
            badge_x = origin["x"] + size["width"] + badge_r + 1
            badge_y = h - origin["y"]
            # Keep badge inside the page bounds.
            badge_x = min(max(badge_r + 1, badge_x), w - badge_r - 1)
            badge_y = min(max(badge_r + 1, badge_y), h - badge_r - 1)
            # Drop shadow for legibility on dark backgrounds.
            c.setFillColor(HexColor("#ffffff"))
            c.setStrokeColor(HexColor("#ffffff"))
            c.circle(badge_x, badge_y, badge_r + 1.2, fill=1, stroke=0)
            c.setFillColor(HexColor(ACCENT_HEX))
            c.setStrokeColor(HexColor(ACCENT_HEX))
            c.circle(badge_x, badge_y, badge_r, fill=1, stroke=1)
            c.setFillColor(HexColor("#ffffff"))
            c.setFont("Helvetica-Bold", 10)
            num_str = str(ann["number"])
            num_w = c.stringWidth(num_str, "Helvetica-Bold", 10)
            c.drawString(badge_x - num_w / 2, badge_y - 3.5, num_str)
        c.save()
        buf.seek(0)
        overlay_reader = PdfReader(buf)
        overlays[page_idx] = overlay_reader.pages[0]
    return overlays


_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def split_frontmatter(md: str) -> tuple[dict, str]:
    """Return (parsed_frontmatter, body). Frontmatter parsing is naive
    (key: value lines). Good enough to recover title / authors."""
    m = _FM_RE.match(md)
    if not m:
        return {}, md
    fm_text = m.group(1)
    body = md[m.end():]
    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def escape_html(s: str) -> str:
    return "".join(_HTML_ESCAPES.get(ch, ch) for ch in s)


def md_to_flowables(body: str, styles) -> list:
    """Naive markdown → ReportLab flowables. Handles ATX headings,
    blank-line paragraph splits, soft-wrapped lines, and bare list
    items prefixed with `- `. Not a complete markdown renderer — good
    enough for the prose notes in the appendix."""
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11, spaceAfter=4)
    body_s = ParagraphStyle(
        "body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=4
    )
    list_s = ParagraphStyle(
        "list",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        leftIndent=18,
        firstLineIndent=-12,
        spaceAfter=2,
    )

    flowables: list = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("# "):
            flowables.append(Paragraph(escape_html(block[2:]), h1))
        elif block.startswith("## "):
            flowables.append(Paragraph(escape_html(block[3:]), h2))
        elif block.startswith("### "):
            flowables.append(Paragraph(escape_html(block[4:]), h3))
        elif all(line.lstrip().startswith(("- ", "* ")) for line in block.splitlines()):
            for line in block.splitlines():
                text = line.lstrip()[2:].strip()
                flowables.append(Paragraph("• " + escape_html(text), list_s))
        else:
            text = escape_html(block).replace("\n", "<br/>")
            flowables.append(Paragraph(text, body_s))
    return flowables


def build_appendix(
    annotations: list[dict], note_md: str, frontmatter: dict, citekey: str, page_size
) -> BytesIO:
    """Render the appendix pages: note first, then numbered list of
    annotations. Page size matches the original PDF for visual
    consistency in the merged output."""
    buf = BytesIO()
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=18, alignment=TA_LEFT, spaceAfter=4
    )
    meta_s = ParagraphStyle(
        "meta", parent=styles["BodyText"], fontSize=10, leading=12, textColor=HexColor("#555555")
    )
    section_s = ParagraphStyle(
        "section",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=8,
        textColor=HexColor(ACCENT_HEX),
    )
    item_s = ParagraphStyle(
        "item",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        spaceAfter=8,
        leftIndent=22,
        firstLineIndent=-22,
    )
    excerpt_s = ParagraphStyle(
        "excerpt",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        leftIndent=22,
        textColor=HexColor("#555555"),
        spaceAfter=2,
    )
    comment_s = ParagraphStyle(
        "comment",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        leftIndent=22,
        spaceAfter=8,
    )

    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        topMargin=40,
        bottomMargin=40,
        leftMargin=40,
        rightMargin=40,
        title=f"Notes — {citekey}",
    )
    flowables: list = []

    flowables.append(Paragraph("Notes &amp; Annotations", title_s))
    if frontmatter.get("title"):
        flowables.append(Paragraph(f"<i>{escape_html(frontmatter['title'])}</i>", meta_s))
    flowables.append(Paragraph(f"<font face='Courier'>{escape_html(citekey)}</font>", meta_s))
    flowables.append(Spacer(1, 10))

    if note_md.strip():
        flowables.append(Paragraph("Notes", section_s))
        flowables.extend(md_to_flowables(note_md, styles))
        flowables.append(PageBreak())

    if annotations:
        flowables.append(Paragraph("Annotations", section_s))
        for ann in annotations:
            n = ann["number"]
            page_label = f"p.{ann['page'] + 1}"
            kind = ann["kind"]
            head = f"<b>{n}.</b> &nbsp;{page_label}&nbsp; <font color='#888888'>· {kind}</font>"
            flowables.append(Paragraph(head, item_s))
            if ann["excerpt"]:
                flowables.append(
                    Paragraph(f"<i>“{escape_html(ann['excerpt'])}”</i>", excerpt_s)
                )
            if ann["comment"]:
                flowables.append(
                    Paragraph(escape_html(ann["comment"]).replace("\n", "<br/>"), comment_s)
                )

    doc.build(flowables)
    buf.seek(0)
    return buf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--citekey", required=True)
    ap.add_argument(
        "--out",
        help="Output path (default: PDFs/{citekey}_annotated.pdf)",
    )
    args = ap.parse_args()

    citekey = args.citekey
    pdf_path = VAULT_ROOT / "PDFs" / f"{citekey}.pdf"
    sidecar_path = VAULT_ROOT / "Annotations" / f"{citekey}.json"
    note_path = VAULT_ROOT / "PaperNotes" / f"{citekey}.md"
    out_path = (
        Path(args.out).expanduser()
        if args.out
        else VAULT_ROOT / "PDFs" / f"{citekey}_annotated.pdf"
    )

    if not pdf_path.is_file():
        print(json.dumps({"error": f"PDF not found: {pdf_path}"}), file=sys.stderr)
        sys.exit(2)

    reader = PdfReader(str(pdf_path))
    annotations = (
        load_user_annotations(sidecar_path) if sidecar_path.is_file() else []
    )

    note_text = note_path.read_text() if note_path.is_file() else ""
    frontmatter, body = split_frontmatter(note_text)

    overlays = (
        build_badge_overlays(annotations, reader) if annotations else {}
    )

    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i in overlays:
            page.merge_page(overlays[i])
        writer.add_page(page)

    # Appendix page size = original PDF page size (use first page's
    # mediabox) so the merged PDF is uniform.
    first_mb = reader.pages[0].mediabox
    appendix_size = (float(first_mb.width), float(first_mb.height))
    appendix_buf = build_appendix(
        annotations, body, frontmatter, citekey, appendix_size
    )
    appendix_reader = PdfReader(appendix_buf)
    for page in appendix_reader.pages:
        writer.add_page(page)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)

    print(
        json.dumps(
            {
                "output": str(out_path),
                "annotations": len(annotations),
                "appendix_pages": len(appendix_reader.pages),
            }
        )
    )


if __name__ == "__main__":
    main()

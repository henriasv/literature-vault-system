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
    appendix builder + overlay builder both consume. Bookmarks are
    excluded — they're invisible in the viewer (live only in the
    right-pane bar) and shouldn't appear as badges in the export."""
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
        if kind == "bookmark":
            continue
        contents = a.get("contents") or ""
        excerpt = contents if kind == "highlight" else ""
        comment = (
            contents
            if kind in ("sticky", "free text")
            else custom.get("comment") or ""
        )
        # segmentRects: per-line geometry for multi-line highlights.
        # Falls back to [rect] for single-line / non-highlight kinds.
        segment_rects = a.get("segmentRects") or [rect]
        out.append({
            "id": a.get("id", ""),
            "page": a.get("pageIndex", 0),
            "rect": rect,
            "segmentRects": segment_rects,
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


def _draw_highlights_and_shapes(
    c: canvas.Canvas, anns: list[dict], page_h: float
) -> None:
    """Paint translucent highlight fills + shape outlines onto the
    canvas. Highlights use segmentRects so multi-line selections track
    each line individually instead of one bounding rectangle that
    would also cover the gap between lines. Shapes (square / circle /
    line / ink) draw their geometric outline — the in-app viewer's
    own renderer drew these, but they aren't in the source PDF, so we
    re-render them here."""
    for ann in anns:
        color_hex = ann.get("color") or "#FFEB3B"
        try:
            col = HexColor(color_hex)
        except Exception:
            col = HexColor("#FFEB3B")
        if ann["subtype"] == SUBTYPE_HIGHLIGHT:
            c.saveState()
            c.setFillColor(col)
            c.setFillAlpha(0.40)
            c.setStrokeAlpha(0.0)
            for seg in ann["segmentRects"]:
                ox = seg["origin"]["x"]
                oy = seg["origin"]["y"]
                sw = seg["size"]["width"]
                sh = seg["size"]["height"]
                pdf_y = page_h - oy - sh
                c.rect(ox, pdf_y, sw, sh, fill=1, stroke=0)
            c.restoreState()
        elif ann["subtype"] in (SUBTYPE_SQUARE, SUBTYPE_CIRCLE):
            r = ann["rect"]
            ox, oy = r["origin"]["x"], r["origin"]["y"]
            sw, sh = r["size"]["width"], r["size"]["height"]
            pdf_y = page_h - oy - sh
            c.saveState()
            c.setStrokeColor(col)
            c.setStrokeAlpha(0.9)
            c.setLineWidth(1.5)
            if ann["subtype"] == SUBTYPE_SQUARE:
                c.rect(ox, pdf_y, sw, sh, fill=0, stroke=1)
            else:
                c.ellipse(ox, pdf_y, ox + sw, pdf_y + sh, fill=0, stroke=1)
            c.restoreState()


def _draw_badges(
    c: canvas.Canvas, anns: list[dict], page_h: float, page_w: float
) -> None:
    """Draw the accent-coloured numbered badge at the top-right corner
    of each annotation's bounding rect. Badges are clamped inside the
    page so a highlight that ends near the right edge doesn't push
    its badge off-canvas."""
    badge_r = 8.0
    for ann in anns:
        origin = ann["rect"]["origin"]
        size = ann["rect"]["size"]
        badge_x = origin["x"] + size["width"] + badge_r + 1
        badge_y = page_h - origin["y"]
        badge_x = min(max(badge_r + 1, badge_x), page_w - badge_r - 1)
        badge_y = min(max(badge_r + 1, badge_y), page_h - badge_r - 1)
        # White halo so the badge stays readable on dark backgrounds.
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


def build_inplace_overlays(
    annotations: list[dict], reader: PdfReader
) -> dict[int, "object"]:
    """Per-page overlay used in `appendix` mode: highlight fills,
    shape outlines, numbered badges. The original PDF dimensions are
    preserved (no margin column)."""
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
        _draw_highlights_and_shapes(c, anns, h)
        _draw_badges(c, anns, h, w)
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


def _styles():
    """Cached set of paragraph styles used by cover + appendix
    builders. Returned fresh each call (reportlab's getSampleStyleSheet
    is process-wide singleton — we layer ours on top)."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=styles["Title"], fontSize=18, alignment=TA_LEFT, spaceAfter=4
        ),
        "meta": ParagraphStyle(
            "meta", parent=styles["BodyText"], fontSize=10, leading=12,
            textColor=HexColor("#555555"),
        ),
        "section": ParagraphStyle(
            "section", parent=styles["Heading2"], fontSize=12,
            spaceBefore=10, spaceAfter=8, textColor=HexColor(ACCENT_HEX),
        ),
        "item": ParagraphStyle(
            "item", parent=styles["BodyText"], fontSize=10, leading=13,
            spaceAfter=4, leftIndent=22, firstLineIndent=-22,
        ),
        "excerpt": ParagraphStyle(
            "excerpt", parent=styles["BodyText"], fontSize=10, leading=13,
            leftIndent=22, textColor=HexColor("#555555"), spaceAfter=2,
        ),
        "comment": ParagraphStyle(
            "comment", parent=styles["BodyText"], fontSize=10, leading=13,
            leftIndent=22, spaceAfter=8,
        ),
        "raw": styles,
    }


def build_cover_pages(
    note_md: str, frontmatter: dict, citekey: str, page_size
) -> BytesIO | None:
    """Build the cover page(s) that go at the FRONT of the export:
    title block + the rendered .md note. Returns None when the note
    is empty (no cover at all)."""
    if not note_md.strip() and not frontmatter.get("title"):
        return None
    buf = BytesIO()
    st = _styles()
    doc = SimpleDocTemplate(
        buf, pagesize=page_size, topMargin=40, bottomMargin=40,
        leftMargin=40, rightMargin=40, title=f"Notes — {citekey}",
    )
    flowables: list = []
    flowables.append(Paragraph("Notes &amp; Annotations", st["title"]))
    if frontmatter.get("title"):
        flowables.append(Paragraph(f"<i>{escape_html(frontmatter['title'])}</i>", st["meta"]))
    flowables.append(
        Paragraph(f"<font face='Courier'>{escape_html(citekey)}</font>", st["meta"])
    )
    flowables.append(Spacer(1, 12))
    if note_md.strip():
        flowables.append(Paragraph("Notes", st["section"]))
        flowables.extend(md_to_flowables(note_md, st["raw"]))
    doc.build(flowables)
    buf.seek(0)
    return buf


def build_tail_appendix(
    annotations: list[dict], page_size
) -> BytesIO | None:
    """Build the tail-end "Annotations" appendix used in `appendix`
    mode — a numbered list mirroring the badges stamped on the PDF
    pages. Returns None if there are no annotations to list."""
    if not annotations:
        return None
    buf = BytesIO()
    st = _styles()
    doc = SimpleDocTemplate(
        buf, pagesize=page_size, topMargin=40, bottomMargin=40,
        leftMargin=40, rightMargin=40, title="Annotations",
    )
    flowables: list = []
    flowables.append(Paragraph("Annotations", st["section"]))
    for ann in annotations:
        n = ann["number"]
        page_label = f"p.{ann['page'] + 1}"
        kind = ann["kind"]
        head = f"<b>{n}.</b> &nbsp;{page_label}&nbsp; <font color='#888888'>· {kind}</font>"
        flowables.append(Paragraph(head, st["item"]))
        if ann["excerpt"]:
            flowables.append(
                Paragraph(f"<i>“{escape_html(ann['excerpt'])}”</i>", st["excerpt"])
            )
        if ann["comment"]:
            flowables.append(
                Paragraph(escape_html(ann["comment"]).replace("\n", "<br/>"), st["comment"])
            )
    doc.build(flowables)
    buf.seek(0)
    return buf


def build_margin_overlay(
    orig_w: float, orig_h: float, margin_w: float, anns: list[dict]
) -> "object":
    """Generate the overlay for a single page in `margin` mode. The
    overlay covers the entire wider page; the left portion paints the
    highlight + badge layer (matching the original-page geometry),
    the right portion renders the per-page annotation list (numbered
    items mirroring the badges, with excerpt + comment). Returns a
    pypdf PageObject ready to merge_page over the widened blank
    canvas."""
    new_w = orig_w + margin_w
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(new_w, orig_h))
    # Faint vertical divider between page and comment column.
    c.saveState()
    c.setStrokeColor(HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.line(orig_w, 8, orig_w, orig_h - 8)
    c.restoreState()
    # In-place highlight + badge layer, anchored to the original page
    # geometry (badges still clamp to `orig_w`, not `new_w`).
    _draw_highlights_and_shapes(c, anns, orig_h)
    _draw_badges(c, anns, orig_h, orig_w)
    # Right-side panel: per-page annotation list. Flow through a Frame
    # so long comments wrap to the column width.
    if anns:
        from reportlab.platypus import Frame
        st = _styles()
        panel_left = orig_w + 8
        panel_bottom = 16
        panel_width = margin_w - 16
        panel_height = orig_h - 32
        frame = Frame(
            panel_left, panel_bottom, panel_width, panel_height,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
            showBoundary=0,
        )
        flowables: list = []
        for ann in anns:
            n = ann["number"]
            head = (
                f"<b>{n}.</b> &nbsp;p.{ann['page'] + 1}"
                f"&nbsp; <font color='#888888'>· {ann['kind']}</font>"
            )
            flowables.append(Paragraph(head, st["item"]))
            if ann["excerpt"]:
                flowables.append(
                    Paragraph(f"<i>“{escape_html(ann['excerpt'])}”</i>", st["excerpt"])
                )
            if ann["comment"]:
                flowables.append(
                    Paragraph(
                        escape_html(ann["comment"]).replace("\n", "<br/>"),
                        st["comment"],
                    )
                )
        frame.addFromList(flowables, c)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--citekey", required=True)
    ap.add_argument(
        "--out",
        help="Output path. Default: PDFs/annotation_outputs/{citekey}_annotated.pdf"
        " — picked so scripted runs (e.g. the librarian agent) end up in a"
        " predictable subfolder.",
    )
    ap.add_argument(
        "--mode",
        choices=("appendix", "margin"),
        default="appendix",
        help=(
            "Annotation rendering mode. 'appendix' (default): note at front, "
            "PDF pages with highlights + numbered badges, annotation list as "
            "tail appendix. 'margin': note at front, each PDF page widened "
            "with a Word-review-style comment column on the right showing "
            "the annotations on that page."
        ),
    )
    args = ap.parse_args()

    citekey = args.citekey
    pdf_path = VAULT_ROOT / "PDFs" / f"{citekey}.pdf"
    sidecar_path = VAULT_ROOT / "Annotations" / f"{citekey}.json"
    note_path = VAULT_ROOT / "PaperNotes" / f"{citekey}.md"
    out_path = (
        Path(args.out).expanduser()
        if args.out
        else VAULT_ROOT / "PDFs" / "annotation_outputs" / f"{citekey}_annotated.pdf"
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

    # Use the original PDF's first-page size as the canonical page size
    # for cover + appendix so the merged output is visually uniform.
    first_mb = reader.pages[0].mediabox
    base_size = (float(first_mb.width), float(first_mb.height))

    writer = PdfWriter()
    cover_pages = 0
    annotated_pages = 0
    appendix_pages = 0

    # 1. Cover (note .md) at the FRONT. Students typically want the
    # overall feedback up top before scanning detailed annotations.
    cover_buf = build_cover_pages(body, frontmatter, citekey, base_size)
    if cover_buf is not None:
        cover_reader = PdfReader(cover_buf)
        for p in cover_reader.pages:
            writer.add_page(p)
        cover_pages = len(cover_reader.pages)

    # 2. Annotated PDF pages — geometry differs by mode.
    if args.mode == "appendix":
        overlays = build_inplace_overlays(annotations, reader) if annotations else {}
        for i, page in enumerate(reader.pages):
            if i in overlays:
                page.merge_page(overlays[i])
            writer.add_page(page)
            annotated_pages += 1
    else:
        # margin mode: widen each page by ~40% to make room for the
        # comment column. Original content sits on the left at native
        # size, comments flow on the right.
        from pypdf import PageObject

        by_page: dict[int, list[dict]] = {}
        for ann in annotations:
            by_page.setdefault(ann["page"], []).append(ann)
        for i, page in enumerate(reader.pages):
            mb = page.mediabox
            orig_w = float(mb.width)
            orig_h = float(mb.height)
            margin_w = orig_w * 0.45
            anns = by_page.get(i, [])
            new_page = PageObject.create_blank_page(width=orig_w + margin_w, height=orig_h)
            new_page.merge_page(page)
            new_page.merge_page(build_margin_overlay(orig_w, orig_h, margin_w, anns))
            writer.add_page(new_page)
            annotated_pages += 1

    # 3. Tail appendix — only in `appendix` mode.
    if args.mode == "appendix":
        appendix_buf = build_tail_appendix(annotations, base_size)
        if appendix_buf is not None:
            appendix_reader = PdfReader(appendix_buf)
            for p in appendix_reader.pages:
                writer.add_page(p)
            appendix_pages = len(appendix_reader.pages)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)

    print(
        json.dumps(
            {
                "output": str(out_path),
                "annotations": len(annotations),
                "mode": args.mode,
                "cover_pages": cover_pages,
                "annotated_pages": annotated_pages,
                "appendix_pages": appendix_pages,
            }
        )
    )


if __name__ == "__main__":
    main()

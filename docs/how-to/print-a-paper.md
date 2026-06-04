# Print a paper

The Viewer prints the active tab's PDF straight to the macOS print sheet via PDFKit (`NSPrintOperation`). No Preview in the loop.

## Shortcuts

| Shortcut | Action |
|---|---|
| ⌘P | Print the original PDF. |
| ⌘⇧P | Print with annotations baked in. |

Both also live under **File** in the menu bar: **Print PDF…** and **Print with Annotations…**.

## What the print sheet shows

The Viewer expands the sheet to Preview's full set of controls:

- Copies, Page range
- Paper size, Orientation
- Scale slider (drives `NSPrintInfo.scalingFactor` — Page Scale None internally so the slider is authoritative)
- Live preview pane

Publisher link annotations (visible blue boxes around citations) are stripped before printing — the original PDF on disk is untouched.

## Annotated print

⌘⇧P (or **File → Print with Annotations…**) runs the same export pipeline the **Export PDF** button uses, picking up your last-chosen mode from `localStorage`:

- **margin** — Word-review style. Annotations are listed in the right margin, vertically aligned with their anchors on the page. Each entry gets an accent badge matching the on-page badge.
- **appendix** — the original PDF, then a numbered list of every annotation as appendix pages.

The notes pane's **Export PDF** split-button is where you switch modes; the print action follows whatever you picked.

## See also

- [Review student work](review-student-work.md) — the print pipeline is what closes the grading loop.
- [Reference: viewer architecture](../reference/viewer-architecture.md) — where `print_pdf` lives in the Rust crate.

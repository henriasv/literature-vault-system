# Review student work

The Viewer has a third top-level mode — **Reviewing** — for grading student assignments. Review papers live in a parallel subtree (`PDFs/reviewing/`, `ReviewNotes/`) so they never appear in your main library, never enter `Bibfiles/`, and never pollute `library.bib`.

This guide assumes you've finished the [tutorial](../tutorial/getting-started.md).

## Switch to Reviewing mode

Top-left segmented control: **Reading · Organizing · Reviewing**. Click **Reviewing**. The left rail switches from the library list to a projects rail; the PDF + notes pane on the right is unchanged.

## Create a project

Click **+ New** at the top of the rail and type a project slug (e.g. `hon2200_v26_project2`). The Viewer creates `<vault>/ReviewNotes/<slug>/` and `<vault>/PDFs/reviewing/<slug>/` on disk.

## File student PDFs

Drop one or more PDFs onto the project row (or first select the project and drop anywhere — drops fall back to the selected project). Each PDF is moved into `PDFs/reviewing/<slug>/<stem>.pdf`; a minimal `ReviewNotes/<slug>/<stem>.md` is written alongside it with `@studentwork` frontmatter and `done: false`.

A post-drop sheet pops up listing the just-filed papers with editable **Title** and **Authors** fields, pre-filled from filename. Save commits the edits; Skip keeps the filename-derived defaults — you can edit later via right-click on the row.

## Read, annotate, take notes

Click a paper to open it on the right. Everything in Reading mode applies: highlights, sticky notes, shapes, the markdown notes pane with `Edit / Preview / Annotations`, ⌘C copy on selected text, hyperlinks open in your default browser. The selected paper is highlighted in the project rail so you can see which one is on screen.

## Mark a paper as graded

Each row has a **Mark done** / **✓ Done reviewing** pill on the right. Clicking it toggles the frontmatter's `done:` field via the backend; the title goes muted when done. Sort and word count keep showing alongside it.

## Sort the list

The project's section header has a **name / added** segmented toggle. **name** sorts alphabetically by title — useful when you set titles to group numbers. The choice persists across reloads.

## Rename / move papers

Right-click a paper row → **Rename / edit metadata…** opens the same sheet as the post-drop flow, pre-filled with the current values. Save patches just the `title` and `authors` fields in the frontmatter; the rest of the note is preserved.

For renaming the **file** (the `<stem>`) or moving between projects, use the `rename_review_paper.py` script — touching the files directly will desync the four artifacts (PDF, Note, Annotation sidecar, frontmatter citekey).

```bash
uv run scripts/rename_review_paper.py \
  --citekey review:<project>:<stem> \
  [--new-stem <new>] [--new-project <slug>]
```

The script pre-checks every collision, moves the files in order, then rewrites the frontmatter `citekey` field; on any failure it rolls back the moves it made. The librarian agent uses this same script for its own renames.

## Print with annotations

⌘P prints the original PDF; ⌘⇧P bakes the highlights/shapes/comments via the export pipeline (using whichever margin/appendix mode you picked in the **Export PDF** split-button) and prints the annotated copy. Both go straight to the macOS print sheet — no Preview in the loop.

## Export the graded copy as a file

The **Export PDF** button in the notes pane writes an annotated copy to disk so you can email or upload it. Choose **margin** (Word-review style — annotations sit in the right margin, y-aligned to their anchors) or **appendix** (annotations as a numbered list after the document).

## Where the files live

See [reference: vault layout — Reviewing-mode subtree](../reference/vault-layout.md#reviewing-mode-subtree) for the on-disk shape and the synthetic `review:<project>:<stem>` citekey scheme.

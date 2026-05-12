# Use the vault with Obsidian

The vault is plain Markdown with YAML frontmatter. Open the same folder in Obsidian and the usual features work out of the box: backlinks, graph view, tag panes, and search across notes.

## Setup

In Obsidian: **File → Open vault → ~/literature-vault** (or wherever you put it).

That's all you need.

## What you can do

- **Browse notes** — `PaperNotes/{citekey}.md` is just Markdown; click around in Obsidian's file explorer.
- **Filter by tag** — Obsidian's tag pane reads the `tags:` array in each note's frontmatter. Topic tags are bare (`chemfrac`); citation tags start with `cite:` (`cite:thesis-ch3`).
- **Backlinks** — wikilink-style references between notes are followed.
- **Collections** — `Collections/{slug}/index.md` is just a Markdown file. The `## Papers` list is a plain bullet list of citekeys; you can edit it by hand if you like, but stick to the conventions in [reference: scripts](../reference/scripts.md) so automated tools keep working.

## Co-editing notes from Obsidian

Both the Viewer and the Librarian preserve everything outside their canonical sections byte-for-byte:

- The Viewer touches the YAML frontmatter and the editor pane contents you actually edit.
- The Librarian touches `## Why`, `## Cleaned Notes`, `## Notes`, and the `abstract:` field in frontmatter only.

Anything else in a note — extra sections, free-form prose, hand-edited tables — survives untouched.

## Bases (optional, advanced)

The vault layout supports Obsidian Bases (the table/board view plugin). You can drop `.base` files under a `Bases/` folder to build filtered views over your library (e.g. "Papers tagged `cite:thesis-3`"). This isn't automated — it's manual Obsidian configuration on your side.

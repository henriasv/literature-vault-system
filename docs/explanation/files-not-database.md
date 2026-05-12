# Files, not a database

The vault has no central database. Notes are Markdown files. BibTeX is `.bib` files. The dedup index is one JSON file. The only SQLite database in the system is `embeddings.db`, and that's regenerable from the notes.

This page is about why that's a deliberate choice.

## What "no database" buys you

**Portability.** The vault is `rsync`-able, `tar`-able, `git`-able. Move it to another machine and it works. Open it in Obsidian, in Vim, in VS Code, in Finder — all of those work because nothing is hiding behind an opaque file format.

**Inspectability.** When something goes wrong, you can read the data with `cat`. When a tool gets a citekey wrong, you can see exactly what went into the filename. When a note is mis-tagged, the fix is `vim PaperNotes/{citekey}.md`. There's no admin UI to learn.

**Forkability.** Want to add a new section to every note? `grep` for what you need, write a one-off script, commit the result. You don't have to schema-migrate; you don't have to write a UI; you don't have to wait for someone to merge your patch.

**Longevity.** Markdown + BibTeX + JSON are formats older than most of the people reading this. They'll outlive any specific tool that processes them. If both the Viewer and the Librarian vanish tomorrow, the vault is still readable, searchable, and citable.

## What "no database" costs you

**Query power.** You can't ask "every paper tagged X published after Y" with one SQL statement. You have to walk the filesystem, parse frontmatter, and filter in your language of choice. For the scale this system targets — thousands of papers, not millions — that's fine. `grep -l 'cite:thesis-3' PaperNotes/*.md` finishes instantly.

**Referential integrity.** Nothing stops a collection's `## Papers` from pointing at a citekey that doesn't exist. The remedy is to keep the writers honest (atomic writes, scripts that validate) and to have a periodic audit, not to push the problem to a database.

**Indexing.** `embeddings.db` exists because vector similarity over a few thousand notes is too slow without an index. That's the one operation where the "no DB" rule yields. The compromise is deliberate: the index is **regenerable** from the notes (`uv run scripts/embed_corpus.py`), so if it corrupts you nuke it and rebuild. It's a cache, not a source of truth.

## How writers stay consistent without a DB

A few small disciplines make this work:

- **Atomic writes.** Every script that touches shared state (`index.json`, `library.bib`, a `Collections/.../index.md`) writes a tempfile in the same directory and renames it into place. No half-written files.
- **Section ownership.** Each writer touches only its canonical sections. The Viewer never edits `## Notes`; the Librarian never edits the body you type. They literally don't overlap.
- **Deterministic identifiers.** Citekeys are computed from the DOI + CrossRef metadata. Two surfaces filing the same paper independently always produce the same citekey, so they file to the same path and the dedup index catches the duplicate.
- **Content-addressed dedup.** `index.json` is keyed by sha256, DOI, and arXiv ID. Anything new gets hashed before write; anything already there is rejected with a pointer to the existing citekey.

The vault is consistent because nothing tries to write to the same bytes at the same time, not because something is mediating writes.

## Related

- [Two surfaces, one vault](two-surfaces-one-vault.md) — why the filesystem is the contract between Viewer and Librarian.
- [Citekeys as identifiers](citekeys-as-identifiers.md) — why the dedup story works.

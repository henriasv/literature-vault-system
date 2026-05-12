# Adopt an existing folder of papers

You already have a folder of PDFs + Markdown notes from some earlier workflow and want to turn it into a Literature Vault.

## Required starting layout

The script expects your directory to already look roughly like this:

```
<your-dir>/
├── PaperNotes/{citekey}.md     # one note per paper
├── PDFs/{citekey}.pdf          # matching PDF
└── Bibfiles/{citekey}.bib      # optional but recommended
```

The filename **must** be the citekey — each note, PDF, and bib for the same paper share the same base name. See [reference: citation keys](../reference/citation-keys.md) for the format.

Notes also need YAML frontmatter with at least the fields listed in [reference: note frontmatter](../reference/note-frontmatter.md). If yours don't, you'll have to refile each paper through `file_paper.py` or `manual_file.py` (see [reference: scripts](../reference/scripts.md)) before the Viewer can use them.

## Steps

1. Move your `PaperNotes/`, `PDFs/`, and (optional) `Bibfiles/` into a single parent directory.

2. Verify that every note has a matching PDF:

   ```bash
   cd <your-dir>
   comm -23 \
     <(ls PaperNotes | sed 's/\.md$//' | sort) \
     <(ls PDFs       | sed 's/\.pdf$//' | sort)
   # any output = notes with no matching PDF
   ```

3. If you already have a `scripts/` directory in there (real files, not a symlink), the adopt step will move it to `scripts.old/` and replace it with a symlink to this repo. Check you haven't customised anything in there first.

4. Run with `--adopt`:

   ```bash
   ./setup/init-vault.sh <your-dir> --adopt
   ```

   The script creates any missing folders (`Inbox/`, `Collections/`, `Projects/`, `Annotations/`, `SI/`, plus `Bibfiles/`/`PDFs/` if absent), replaces `scripts/` with a symlink to this repo (backing up an existing directory to `scripts.old/`), and skips `index.json`, `library.bib`, and `.gitignore` if they already exist (adopt mode never clobbers).

5. Rebuild `library.bib` from your existing Bibfiles:

   ```bash
   uv run scripts/build_library_bib.py
   ```

6. Populate the dedup index. There is currently no bulk-rebuild script — re-file each PDF through `scripts/file_paper.py --in-place` so the index gets a sha256 / DOI / arXiv entry per paper. See [Known limitations](../KNOWN_LIMITATIONS.md) for the missing helper.

You should now be able to open the directory in the Viewer.

## Troubleshooting

- **Notes missing frontmatter.** Refile each affected paper via `scripts/file_paper.py --in-place --pdf <path> --doi <doi>` (or `manual_file.py` for items without a DOI).
- **Citekey naming mismatch.** If your existing filenames don't follow the citekey scheme, rename them to match before adopting — the Viewer keys everything off the basename.

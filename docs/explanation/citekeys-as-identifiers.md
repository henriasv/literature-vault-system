# Citekeys as identifiers

The citekey is the primary identifier for every paper in the vault. Filenames are citekeys; cross-references between notes are citekeys; BibTeX entries are keyed by them; the Librarian addresses papers by them in chat.

This page is about why citekeys carry that load instead of, say, a UUID or a database row id.

## What a citekey looks like

```
livne2008-prl-physrevlett-101-264301
```

`{first-author}{year}-{journal-abbrev}-{slugified-DOI-suffix}`. The full algorithm is in [reference: citation keys](../reference/citation-keys.md).

## Three properties make it work

### 1. Deterministic

Given a DOI, the algorithm computes the same citekey on every machine, in any language, at any time. There's no "next ID" that requires a central allocator, no UUID generator, no timestamp.

This is what lets the Viewer and the Librarian file the same paper independently. They both call `doi2bib.py`, both get the same citekey, both write to the same path. Whichever one runs second hits the dedup check (the sha256 already exists in `index.json`) and reports the existing citekey instead of overwriting.

### 2. Stable

The inputs are immutable: the DOI is fixed at publication; CrossRef's author and year fields are frozen in the same place. So once a citekey is assigned, **it never changes**. Old notes, old commits, old chats keep working — every citekey ever mentioned still resolves.

This matters a lot in practice. A paper's note file might be rewritten dozens of times over the course of a thesis. Other notes link to it. Manuscripts cite it from LaTeX. If the identifier could rotate, every reference would have to be updated. With a stable citekey, the identifier *is* the cross-reference.

### 3. Human-readable

Compare:

```
livne2008-prl-physrevlett-101-264301
e54a1b62-7f2c-4d8a-9c1d-87d4f5a2e3b1
```

A UUID would give us all the determinism and stability properties. But you also want to scan `ls PaperNotes/` and have it mean something. You want `\cite{livne2008-prl-…}` in a LaTeX manuscript to be readable when you come back to it. You want a Telegram message that says "Filed as `livne2008-…`" to tell you something useful without needing to look anything up.

The `{author}{year}` prefix gives that — it's not load-bearing for uniqueness (the DOI suffix is), it's just for the human reading the filename.

## Why not just use the DOI

The DOI is what the citekey is derived from, and it's already unique. We don't use it directly because:

- DOIs contain characters that are awkward as filenames (`/` for sure; sometimes `:`, `(`, `)`).
- DOIs aren't valid BibTeX keys without escaping.
- DOIs don't include the year or author, which is the part of the readable filename people actually find useful.

So citekeys are basically slugified DOIs with the author/year prefix tacked on for readability — the slug carries the uniqueness, the prefix carries the human meaning.

## Pre-digital papers

A small minority of items genuinely have no DOI and no arXiv ID — old books, theses, pre-1990s papers. For those, the manual fallback citekey is `{author}{year}-{short-title-slug}`. These are rare, marked with a `% manual-key` comment in the BibTeX entry, and assigned by hand.

## Related

- [Files, not a database](files-not-database.md) — why deterministic filenames work as primary keys.
- [Reference: citation keys](../reference/citation-keys.md) — the precise algorithm.

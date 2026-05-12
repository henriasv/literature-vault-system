# Citation keys

Citation keys are permanent, globally unique identifiers used throughout the vault to reference papers. Once assigned, a key **never changes**.

## Algorithm

Given a DOI, the canonical citation key is:

```
key = "{author}{year}-{journal}-{doi_suffix}"
```

where `doi_suffix` is the slugified DOI suffix with any redundant journal prefix stripped.

### Steps

1. **Resolve metadata.** Fetch `https://api.crossref.org/works/{doi}`.

2. **Extract first author** (`author`):
   - Take the `family` name of the first entry in the `author` array.
   - If there's no `author` array (consortia, standards bodies), take the first word of the first entry in `editor`, or failing that, use `"unknown"`.
   - Normalize: Unicode NFKD decomposition → strip combining marks → lowercase → keep only `[a-z]`.

3. **Extract year** (`year`):
   - Check CrossRef date fields in order: `published`, `published-print`, `published-online`, `issued`.
   - Take the first `date-parts[0][0]` that is non-null.
   - If no year is found, use `"XXXX"`.

4. **Extract journal abbreviation** (`journal`):
   - Look up the full journal name in `JOURNAL_ABBREV` in `doi2bib.py`.
   - If not found, fall back to initials of the first 4 words (and add to the map).

5. **Compute DOI suffix** (`doi_suffix`):
   - Take everything after the **first** `/` in the DOI (strip the `10.XXXX/` registrant prefix).
   - Lowercase.
   - Replace every character that is not `[a-z0-9]` with `-`.
   - Collapse consecutive `-` into a single `-`.
   - Strip leading and trailing `-`.
   - If the result starts with `{journal}-`, strip that prefix (avoids `pnas-pnas-…` redundancy).

6. **Assemble**: `f"{author}{year}-{journal}-{doi_suffix}"`.

### ArXiv fallback (no DOI)

```
key = "{author}{year}-arxiv-{arxiv_slug}"
```

`arxiv_slug` is the arXiv ID with `.` replaced by `-`. Author and year come from arXiv metadata, normalized the same way.

### Manual fallback (no DOI, no arXiv)

For books, theses, and pre-digital papers truly absent from CrossRef/DataCite:

```
key = "{author}{year}-{short_title_slug}"
```

`short_title_slug` is the first 3–5 significant words of the title, slugified by the same rules. These keys are rare and assigned manually; mark them with a `% manual-key` comment in the BibTeX entry.

## Examples

| DOI | Journal | Key |
|---|---|---|
| `10.1103/PhysRevLett.126.236001` | PRL | `cheng2021-prl-physrevlett-126-236001` |
| `10.1038/s41467-023-36329-y` | Nat. Commun. | `musaelian2023-natcommun-s41467-023-36329-y` |
| `10.1021/acs.jpclett.4c00605` | JPCL | `stolte2024-jpcl-4c00605` |
| `10.1073/pnas.2501728122` | PNAS | `juel2025-pnas-2501728122` |
| `10.1098/rsos.220099` | RSOS | `haeffel2022-rsos-220099` |
| `10.1038/s41586-025-09844-9` | Nature | `aczel2026-nature-s41586-025-09844-9` |

ArXiv example: arXiv `2305.10141` by Musaelian → `musaelian2023-arxiv-2305-10141`.

## Properties

| Property | Guarantee |
|---|---|
| **Stable** | Derived from immutable identifiers (DOI + CrossRef metadata frozen at publication). |
| **Unique** | DOI suffixes are globally unique by definition. The `author{year}` prefix is for human readability only. |
| **Deterministic** | Given a DOI, any agent computes the same key by following this algorithm. |

## Implementation

The reference implementation is `make_canonical_key()` in `scripts/doi2bib.py`.

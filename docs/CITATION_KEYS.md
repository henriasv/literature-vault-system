# Citation Key Specification

Citation keys are permanent, globally unique identifiers used throughout the wiki and research notes to reference papers. Once assigned, a key **never changes**.

## Algorithm

Given a DOI, the canonical citation key is computed as:

```
key = "{author}{year}-{journal}-{doi_suffix}"
```

where `doi_suffix` is the slugified DOI suffix with any redundant journal prefix stripped.

### Steps

1. **Resolve metadata**: Fetch `https://api.crossref.org/works/{doi}` to get structured metadata.

2. **Extract first author** (`author`):
   - Take the `family` name of the first entry in the `author` array.
   - If no `author` array exists (consortia, standards bodies), take the first word of the first entry in the `editor` array, or failing that, use `"unknown"`.
   - Normalize: Unicode NFKD decomposition → strip combining marks → lowercase → keep only `[a-z]`.

3. **Extract year** (`year`):
   - Check CrossRef date fields in order: `published`, `published-print`, `published-online`, `issued`.
   - Take the first `date-parts[0][0]` that is non-null.
   - If no year is found, use `"XXXX"`.

4. **Extract journal abbreviation** (`journal`):
   - Look up the full journal name in `JOURNAL_ABBREV` in `doi2bib.py`.
   - If not found, fall back to initials of the first 4 words (and add to the map).

5. **Compute DOI suffix** (`doi_suffix`):
   - Take the DOI suffix: everything after the **first** `/` (i.e., strip the `10.XXXX/` registrant prefix).
   - Lowercase the suffix.
   - Replace every character that is not `[a-z0-9]` with `-`.
   - Collapse consecutive `-` into a single `-`.
   - Strip leading and trailing `-`.
   - If the result starts with `{journal}-`, strip that prefix (avoids redundancy when the journal abbreviation is already embedded in the DOI suffix, e.g. PNAS, RSOS).

6. **Assemble**: `f"{author}{year}-{journal}-{doi_suffix}"`

### ArXiv fallback (no DOI)

```
key = "{author}{year}-arxiv-{arxiv_slug}"
```

- `arxiv_slug`: Take the arXiv ID (e.g., `2305.10141`), replace `.` with `-`.
- Author and year are extracted from arXiv metadata using the same normalization.

### Manual fallback (no DOI, no arXiv)

For books, theses, and other items without a DOI or arXiv ID:

```
key = "{author}{year}-{short_title_slug}"
```

- `short_title_slug`: Take the first 3-5 significant words of the title, slugify with the same rules as `doi_slug`.
- These keys are rare and assigned manually. They should be marked with a `% manual-key` comment in the BibTeX entry.

## Examples

| DOI | Journal | Key |
|-----|---------|-----|
| `10.1103/PhysRevLett.126.236001` | PRL | `cheng2021-prl-physrevlett-126-236001` |
| `10.1038/s41467-023-36329-y` | Nat. Commun. | `musaelian2023-natcommun-s41467-023-36329-y` |
| `10.1021/acs.jpclett.4c00605` | JPCL | `stolte2024-jpcl-4c00605` ← `acs-jpclett` stripped |
| `10.1073/pnas.2501728122` | PNAS | `juel2025-pnas-2501728122` ← `pnas` stripped |
| `10.1098/rsos.220099` | RSOS | `haeffel2022-rsos-220099` ← `rsos` stripped |
| `10.1038/s41586-025-09844-9` | Nature | `aczel2026-nature-s41586-025-09844-9` |

ArXiv example: arXiv `2305.10141` by Musaelian → `musaelian2023-arxiv-2305-10141`

## Properties

| Property | Guarantee |
|----------|-----------|
| **Stable** | Derived from immutable identifiers (DOI + CrossRef metadata frozen at publication). Keys never change once assigned. |
| **Unique** | DOI suffixes are globally unique by definition. The author+year prefix is for human readability only. |
| **Deterministic** | Given a DOI, any agent can compute the canonical key by following this algorithm. Requires a CrossRef lookup, but the result is deterministic. |

## Existing keys

Keys created before this spec (format `firstauthor-journalabbrev-year`) have been migrated to the new format. No legacy keys remain in the wiki.

## Implementation

The reference implementation is in `scripts/doi2bib.py` — see the `make_canonical_key()` function.

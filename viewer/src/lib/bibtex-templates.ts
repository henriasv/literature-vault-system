/**
 * BibTeX entry templates for manual filing. Used by InboxFindModal and
 * ReidentifyModal when CrossRef doesn't find a match (books, theses,
 * standards, web pages, preprints without DOIs, etc.).
 *
 * Each template includes the entry type and a placeholder citekey that the
 * user is expected to replace. Fields use the conventional 8-space indent
 * BibTeX style so they line up after `=`.
 */

export interface BibtexTemplate {
  /** Short label for the dropdown. */
  label: string;
  /** BibTeX entry type (without the `@`). */
  type: string;
  /** Pre-filled BibTeX body the user edits. */
  template: string;
  /** One-line hint shown beneath the textarea. */
  hint?: string;
}

/* The placeholder citekey on each template is ignored — the canonical
 * one is recomputed from the parsed author/year/title (and DOI/arXiv
 * eprint if you fill those in) by `scripts/manual_file.py`, same way
 * the agent's `file_paper.py` does. So don't worry about typing it
 * "right"; just leave it as-is. The `% manual-key` comment is dropped
 * on write since the key is no longer manual once we mint one. */
export const bibtexTemplates: BibtexTemplate[] = [
  {
    label: "Journal article",
    type: "article",
    template: `@article{CITEKEY_AUTO_FROM_FIELDS,
  author  = {Lastname, Firstname and Lastname, Firstname},
  title   = {{Title of the paper}},
  journal = {Journal Name},
  year    = {2026},
  volume  = {},
  number  = {},
  pages   = {},
  doi     = {},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
    hint: "Citekey above is auto-generated from author + year + title/DOI on save — don't bother editing the @article{…} header. Use only when the paper has no DOI; otherwise prefer CrossRef search.",
  },
  {
    label: "Book",
    type: "book",
    template: `@book{CITEKEY_AUTO_FROM_FIELDS,
  author    = {Lastname, Firstname},
  title     = {{Book title}},
  publisher = {Publisher},
  year      = {2026},
  address   = {City},
  isbn      = {},
  edition   = {},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Book chapter",
    type: "incollection",
    template: `@incollection{CITEKEY_AUTO_FROM_FIELDS,
  author    = {Lastname, Firstname},
  title     = {{Chapter title}},
  booktitle = {{Book title}},
  editor    = {Editor, Firstname},
  publisher = {Publisher},
  year      = {2026},
  pages     = {},
  address   = {City},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "PhD thesis",
    type: "phdthesis",
    template: `@phdthesis{CITEKEY_AUTO_FROM_FIELDS,
  author = {Lastname, Firstname},
  title  = {{Thesis title}},
  school = {University},
  year   = {2026},
  type   = {PhD thesis},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Master's thesis",
    type: "mastersthesis",
    template: `@mastersthesis{CITEKEY_AUTO_FROM_FIELDS,
  author = {Lastname, Firstname},
  title  = {{Thesis title}},
  school = {University},
  year   = {2026},
  type   = {Master's thesis},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Student work (paper / project)",
    type: "studentwork",
    template: `@studentwork{CITEKEY_AUTO_FROM_FIELDS,
  author      = {Lastname, Firstname},
  title       = {{Assignment title}},
  year        = {2026},
  course      = {Course code or name},
  institution = {University},
  type        = {Term paper},
  note        = {},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
    hint: "Non-standard @studentwork entry type for grading / commenting on student assignments. Set `type` to e.g. \"Term paper\", \"Project report\", \"Lab report\". `course` is custom — keep it short so it shows nicely in the library.",
  },
  {
    label: "Conference paper",
    type: "inproceedings",
    template: `@inproceedings{CITEKEY_AUTO_FROM_FIELDS,
  author    = {Lastname, Firstname and Lastname, Firstname},
  title     = {{Paper title}},
  booktitle = {Proceedings of the …},
  year      = {2026},
  pages     = {},
  publisher = {Publisher},
  doi       = {},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Technical report",
    type: "techreport",
    template: `@techreport{CITEKEY_AUTO_FROM_FIELDS,
  author      = {Lastname, Firstname},
  title       = {{Report title}},
  institution = {Institution},
  year        = {2026},
  number      = {},
  type        = {Technical Report},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Preprint / arXiv",
    type: "misc",
    template: `@misc{CITEKEY_AUTO_FROM_FIELDS,
  author       = {Lastname, Firstname},
  title        = {{Preprint title}},
  year         = {2026},
  eprint       = {2601.12345},
  archivePrefix = {arXiv},
  primaryClass = {cond-mat.soft},
  url          = {https://arxiv.org/abs/2601.12345},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
    hint: "Citekey is auto-generated from the fields below. If the arXiv ID is known, prefer the CrossRef / arXiv auto-intake path.",
  },
  {
    label: "Website / blog post",
    type: "online",
    template: `@online{CITEKEY_AUTO_FROM_FIELDS,
  author       = {Lastname, Firstname},
  title        = {{Page title}},
  year         = {2026},
  url          = {https://example.com/path},
  urldate      = {2026-05-11},
  organization = {Site Name},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
  {
    label: "Generic (misc)",
    type: "misc",
    template: `@misc{CITEKEY_AUTO_FROM_FIELDS,
  author       = {Lastname, Firstname},
  title        = {{Title}},
  year         = {2026},
  howpublished = {\\url{https://...}},
  note         = {},
  % citekey above is ignored — minted from author + year + title/DOI on save
}`,
  },
];

export function findTemplate(type: string): BibtexTemplate | undefined {
  return bibtexTemplates.find((t) => t.type === type);
}

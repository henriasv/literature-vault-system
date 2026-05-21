import { invoke } from "@tauri-apps/api/core";

export interface PaperMeta {
  citekey: string;
  title: string;
  authors: string[];
  authorCount?: number;
  year: number;
  journal: string | null;
  doi: string | null;
  arxivId: string | null;
  added: string;
  tags: string[];
  abstract: string | null;
  sha256Pdf: string;
  hasNote: boolean;
  hasPdf: boolean;
  /** Review-mode only. Whitespace-separated word count of the note body. */
  wordCount?: number;
  /** Review-mode only. `true` when the paper is marked as graded. */
  done?: boolean;
}

export interface Tab {
  citekey: string;
  pdfPage: number;
  pdfZoom: number | "auto";
  scrollPos: { pdf: number; note: number };
  /** When true, this tab occupies the single ephemeral "preview" slot
   *  — single-clicking another paper replaces its content rather than
   *  appending a new tab. At most one preview tab exists at any time;
   *  cmd/middle-click and double-click open permanent tabs (preview =
   *  false) and never touch the preview slot. */
  preview?: boolean;
}

export interface Session {
  tabs: Tab[];
  activeIndex: number;
  splitRatio: number;
  libraryCollapsed: boolean;
  libraryWidth: number;
}

export interface SearchHit {
  citekey: string;
  score: number;
}

export interface EmbedServerHealth {
  ok: boolean;
  default: string;
  registered: string[];
  loaded: string[];
  uptimeSec: number;
  idleSec: number;
  /** Set when the request failed (server down etc). */
  error?: string;
}

export async function listPapers(): Promise<PaperMeta[]> {
  return await invoke<PaperMeta[]>("list_papers");
}

export async function paperMeta(citekey: string): Promise<PaperMeta> {
  return await invoke<PaperMeta>("paper_meta", { citekey });
}

export async function readNote(citekey: string): Promise<string> {
  return await invoke<string>("read_note", { citekey });
}

export async function writeNote(citekey: string, contents: string): Promise<void> {
  return await invoke<void>("write_note", { citekey, contents });
}

/** Replace the `tags:` block in a paper's frontmatter atomically. Returns the
 *  full new file contents so the editor can update its in-memory baseline before
 *  the disk-watcher fires `note:changed` (avoiding a spurious banner). */
export async function setTags(citekey: string, tags: string[]): Promise<string> {
  return await invoke<string>("set_tags", { citekey, tags });
}

/** Concatenate the BibTeX entries for the given citekeys (one per line of
 *  Bibfiles/{citekey}.bib). Missing bib files are emitted as a "% missing"
 *  comment so the caller knows about the gap. */
export async function readBibtex(citekeys: string[]): Promise<string> {
  return await invoke<string>("read_bibtex", { citekeys });
}

export async function pdfPathFor(citekey: string): Promise<string> {
  return await invoke<string>("pdf_path_for", { citekey });
}

export async function vaultRootPath(): Promise<string> {
  return await invoke<string>("vault_root_path");
}

/** Same as `vaultRootPath` but with $HOME replaced by `~` for compact display. */
export async function vaultRootDisplay(): Promise<string> {
  return await invoke<string>("vault_root_display");
}

/** Re-identify an already-filed paper by picking a different CrossRef DOI.
 *  Currently a stub on the Rust side — throws an explanatory error. */
export async function reassignWithDoi(citekey: string, newDoi: string): Promise<void> {
  await invoke("reassign_with_doi", { citekey, newDoi });
}

/** Re-identify an already-filed paper with a user-typed BibTeX entry.
 *  For sources CrossRef doesn't index. Stub on the Rust side. */
export async function reassignWithBibtex(citekey: string, bibtex: string): Promise<void> {
  await invoke("reassign_with_bibtex", { citekey, bibtex });
}

/** Read the per-paper annotation sidecar (EmbedPDF's `AnnotationTransferItem[]`
 *  serialised as JSON). Returns `""` when there are no annotations yet. */
export async function readAnnotations(citekey: string): Promise<string> {
  return await invoke<string>("read_annotations", { citekey });
}

/** Write the per-paper annotation sidecar. Empty / `[]` body deletes the
 *  sidecar instead of writing an empty array — keeps the vault tidy. */
export async function writeAnnotations(citekey: string, json: string): Promise<void> {
  await invoke("write_annotations", { citekey, json });
}

export async function dropToInbox(pdfPaths: string[]): Promise<string[]> {
  return await invoke<string[]>("drop_to_inbox", { pdfPaths });
}

/** Filing outcome for one PDF in a `dropAndFile` batch. Mirrors the
 *  `FilingOutcome` enum on the Rust side. The viewer renders one
 *  toast per outcome (success / duplicate / no-id / error / scripts
 *  missing). */
export interface FilingOutcome {
  inboxPath: string;
  status:
    | "filed"
    | "duplicate"
    | "no-identifier"
    | "error"
    | "scripts-missing";
  citekey: string | null;
  title: string | null;
  detail: string | null;
}

/** Drop PDFs into the Inbox AND run the vault's filing scripts on
 *  each — the canonical citekey is whatever scripts/file_paper.py
 *  produces, so a viewer-filed paper is indistinguishable from an
 *  agent-filed one. Falls back gracefully (returns "scripts-missing"
 *  outcomes) if the vault doesn't carry the scripts. */
export async function dropAndFile(pdfPaths: string[]): Promise<FilingOutcome[]> {
  return await invoke<FilingOutcome[]>("drop_and_file", { pdfPaths });
}

/** One PDF filed into a review project (student-work grading flow). The
 *  Rust side copies the PDF to `PDFs/reviewing/<project>/<stem>.pdf` and
 *  creates a minimal `ReviewNotes/<project>/<stem>.md` with @studentwork
 *  frontmatter. No DOI / CrossRef lookup, no library.bib mutation. */
export interface ReviewFilingOutcome {
  /** `review:<project>:<stem>` on success, empty on error. */
  citekey: string;
  status: "filed" | "error";
  detail?: string | null;
  sourceName: string;
}

export async function dropToReviewProject(
  pdfPaths: string[],
  project: string,
): Promise<ReviewFilingOutcome[]> {
  return await invoke<ReviewFilingOutcome[]>("drop_to_review_project", { pdfPaths, project });
}

/** One PDF currently sitting in `Inbox/`. Files with the same DOI as
 *  an already-filed paper end up here too (the dedup check refuses to
 *  clobber); files without an extractable DOI/arXiv stay here until a
 *  human (or the agent, on its next sweep) helps them along. */
export interface InboxItem {
  path: string;
  filename: string;
  sizeBytes: number;
  modifiedAt: string;
}

export async function listInbox(): Promise<InboxItem[]> {
  return await invoke<InboxItem[]>("list_inbox");
}

/** Re-run the auto-file pipeline on a PDF that's already in the Inbox.
 *  Useful if scripts/file_paper.py was installed after the initial
 *  drop, or if the user renamed the file to embed a DOI hint. */
export async function inboxRetryFile(path: string): Promise<FilingOutcome> {
  return await invoke<FilingOutcome>("inbox_retry_file", { path });
}

/** Delete a PDF from the Inbox. The backend refuses paths that resolve
 *  outside the Inbox directory, so this can't be coerced into deleting
 *  a filed PDF or note. */
export async function inboxDelete(path: string): Promise<void> {
  return await invoke<void>("inbox_delete", { path });
}

/** One candidate returned by `scripts/crossref_search.py`. Used in the
 *  Inbox UI when DOI extraction failed and the user is filling in
 *  title/author/year hints to find the paper manually. */
export interface CrossrefCandidate {
  doi: string | null;
  title: string | null;
  firstAuthor: string | null;
  nAuthors: number | null;
  year: number | null;
  type: string | null;
  score: number | null;
}

/** Query CrossRef via the vault's `scripts/crossref_search.py`. At
 *  least one of title / author / query is required. Returns candidates
 *  ranked by the CrossRef relevance score. */
export async function searchCrossref(args: {
  title?: string;
  author?: string;
  query?: string;
  year?: number;
}): Promise<CrossrefCandidate[]> {
  return await invoke<CrossrefCandidate[]>("search_crossref", args);
}

/** File an Inbox PDF with a DOI the user picked from the CrossRef
 *  search results. Same canonical path as the auto-file flow once a
 *  DOI is known, so the resulting citekey + BibTeX are identical. */
export async function inboxFileWithDoi(
  path: string,
  doi: string,
): Promise<FilingOutcome> {
  return await invoke<FilingOutcome>("inbox_file_with_doi", { path, doi });
}

/** File an Inbox PDF with a user-typed BibTeX entry — for sources CrossRef
 *  doesn't index. Stub on the Rust side. */
export async function inboxFileWithBibtex(
  path: string,
  bibtex: string,
): Promise<FilingOutcome> {
  return await invoke<FilingOutcome>("inbox_file_with_bibtex", { path, bibtex });
}

/** Best-guess `@misc{…}` BibTeX stub extracted from the PDF's own
 *  metadata (XMP → /Info → first-page text). Returns an empty string
 *  when the vault doesn't carry `scripts/extract_pdf_meta.py` so the
 *  caller can fall back to the static template. */
export async function inboxExtractBibtexStub(path: string): Promise<string> {
  return await invoke<string>("inbox_extract_bibtex_stub", { path });
}

/** Full CrossRef record (or DataCite fallback) for one DOI, as the
 *  raw JSON string the API returned. Used by the "Details" expander
 *  on each CrossRef search candidate so the user can see everything
 *  before committing to file. */
export async function fetchCrossrefRecord(doi: string): Promise<string> {
  return await invoke<string>("fetch_crossref_record", { doi });
}

/** Result of the three-tier identifier scan inside `extract_ids.py`. Either
 *  id may be null; `source` reports where the id was found so the UI can
 *  signal reliability ("from metadata" is more trustworthy than "from raw
 *  bytes" which could be a false positive matching a citation). */
export interface ExtractedIds {
  doi: string | null;
  arxivId: string | null;
  source: string;
}

/** Run `extract_ids.py` on a specific PDF path (any path, not necessarily in
 *  the Inbox). Used by the Re-identify modal's "Auto-detect" tab. */
export async function extractIdsFromPdf(path: string): Promise<ExtractedIds> {
  return await invoke<ExtractedIds>("extract_ids_from_pdf", { path });
}

export async function loadSessionRaw(): Promise<string> {
  return await invoke<string>("load_session");
}

export async function saveSessionRaw(json: string): Promise<void> {
  return await invoke<void>("save_session", { json });
}

export async function loadTabStateRaw(citekey: string): Promise<string> {
  return await invoke<string>("load_tab_state", { citekey });
}

export async function saveTabStateRaw(citekey: string, json: string): Promise<void> {
  return await invoke<void>("save_tab_state", { citekey, json });
}

export async function startIndexWatch(): Promise<void> {
  return await invoke<void>("start_index_watch");
}

export async function windowAction(action: string): Promise<void> {
  return await invoke<void>("window_action", { action });
}

export async function embedServerHealth(): Promise<EmbedServerHealth> {
  return await invoke<EmbedServerHealth>("embed_server_health");
}

export async function searchSemantic(query: string, limit = 50): Promise<SearchHit[]> {
  return await invoke<SearchHit[]>("search_semantic", { query, limit });
}

// ---- Collections ----------------------------------------------------------

export interface Collection {
  name: string;
  slug: string;
  description: string | null;
  created: string | null;
  updated: string | null;
  papers: string[];
  hasChildren: boolean;
}

export async function listCollections(): Promise<Collection[]> {
  return await invoke<Collection[]>("list_collections");
}

export async function collectionAdd(slug: string, citekey: string): Promise<Collection> {
  return await invoke<Collection>("collection_add", { slug, citekey });
}

export async function collectionRemove(slug: string, citekey: string): Promise<Collection> {
  return await invoke<Collection>("collection_remove", { slug, citekey });
}

export async function collectionCreate(
  slug: string,
  name?: string,
  description?: string,
): Promise<Collection> {
  return await invoke<Collection>("collection_create", { slug, name, description });
}

export async function collectionDelete(slug: string): Promise<void> {
  return await invoke<void>("collection_delete", { slug });
}

export async function collectionRename(oldSlug: string, newSlug: string): Promise<Collection> {
  return await invoke<Collection>("collection_rename", { oldSlug, newSlug });
}

/**
 * Split a note's full text into the leading frontmatter block (including both `---`
 * fences and their newlines) and the body that follows. Returns `null` when the file
 * doesn't have a valid `---\n…\n---\n` block at the very start, in which case callers
 * should fall back to raw editing.
 */
export function splitNote(contents: string): { frontmatter: string; body: string } | null {
  // Defensive BOM strip — the Rust parser does the same.
  const text = contents.startsWith("﻿") ? contents.slice(1) : contents;
  let cursor: number;
  if (text.startsWith("---\n")) cursor = 4;
  else if (text.startsWith("---\r\n")) cursor = 5;
  else return null;
  // Walk lines after the opening fence; accept the next line that is exactly "---".
  while (cursor < text.length) {
    const nl = text.indexOf("\n", cursor);
    const lineEnd = nl === -1 ? text.length : nl;
    const line = text.substring(cursor, lineEnd).replace(/\r$/, "");
    if (line === "---") {
      const fenceEnd = nl === -1 ? text.length : nl + 1;
      // Re-anchor offsets back to the original `contents` (account for any BOM strip).
      const offset = contents.length - text.length;
      return {
        frontmatter: contents.substring(0, fenceEnd + offset),
        body: contents.substring(fenceEnd + offset),
      };
    }
    if (nl === -1) break;
    cursor = nl + 1;
  }
  return null;
}

/** Display label for a paper: "{first_author} {year}", with "et al." when authors are truncated. */
export function paperLabel(p: PaperMeta): string {
  if (p.authors.length === 0) return `${p.year}`;
  const first = p.authors[0].split(",")[0].trim();
  const etAl = p.authorCount !== undefined && p.authorCount > p.authors.length;
  return etAl ? `${first} et al. ${p.year}` : `${first} ${p.year}`;
}

/** Single-line meta row: "first_author year · journal". */
export function paperSubline(p: PaperMeta): string {
  const lbl = paperLabel(p);
  return p.journal ? `${lbl} · ${p.journal}` : lbl;
}

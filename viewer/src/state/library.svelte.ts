import {
  embedServerHealth,
  listPapers,
  searchSemantic,
  type EmbedServerHealth,
  type PaperMeta,
  type SearchHit,
} from "../lib/vault";
import { prefsState } from "./prefs.svelte";
import { membersOf } from "./collections.svelte";

/** "opened" sorts by last-opened time (data from prefsState.recents) so the
 *  user can browse "what have I been reading?" inside the regular All view —
 *  the dedicated Recent section was redundant once this sort key existed. */
export type SortKey = "added" | "opened" | "year" | "journal" | "title";
export type Section = "all" | "tags" | "manuscripts";
export type SearchMode = "metadata" | "semantic";

interface LibraryState {
  papers: PaperMeta[];
  loadError: string | null;
  loading: boolean;

  // Filters
  query: string;
  /** Tag filter — papers must have all of these tags (intersection). Driven by
   *  the clickable chips in the note metadata header; cleared via the X chip
   *  next to the search bar. */
  selectedTags: string[];
  /** When set, the library list is restricted to papers in this collection
   *  (slug). The light browse-only picker in the library pane sets this; the
   *  full collections panel does too. */
  selectedCollection: string | null;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  section: Section;

  // Semantic search
  searchMode: SearchMode;
  semanticResults: SearchHit[] | null;
  semanticLoading: boolean;
  semanticError: string | null;
  embedHealth: EmbedServerHealth | null;
  /** Set true while we wait for the first semantic query to come back warm. */
  semanticWarming: boolean;
}

export const libraryState = $state<LibraryState>({
  papers: [],
  loadError: null,
  loading: false,
  query: "",
  selectedTags: [],
  selectedCollection: null,
  sortKey: "added",
  sortDir: "desc",
  section: "all",
  searchMode: "metadata",
  semanticResults: null,
  semanticLoading: false,
  semanticError: null,
  embedHealth: null,
  semanticWarming: false,
});

let inflight: Promise<void> | null = null;

export async function refreshLibrary(): Promise<void> {
  if (inflight) return inflight;
  libraryState.loading = true;
  libraryState.loadError = null;
  inflight = (async () => {
    try {
      libraryState.papers = await listPapers();
    } catch (e) {
      libraryState.loadError = String(e);
    } finally {
      libraryState.loading = false;
      inflight = null;
    }
  })();
  return inflight;
}

export function paperByCitekey(citekey: string): PaperMeta | undefined {
  return libraryState.papers.find((p) => p.citekey === citekey);
}

/** Every tag known across the loaded library, sorted alpha. Used as the
 *  autocomplete source for the inline tag editor in the note metadata header. */
export function allTags(): string[] {
  const set = new Set<string>();
  for (const p of libraryState.papers) {
    for (const t of p.tags) set.add(t);
  }
  return [...set].sort();
}

/** Optimistic in-place update of one paper's tags. Used by the inline editor so
 *  the metadata header re-renders immediately without waiting for refreshLibrary. */
export function patchPaperTags(citekey: string, tags: string[]): void {
  const idx = libraryState.papers.findIndex((p) => p.citekey === citekey);
  if (idx < 0) return;
  libraryState.papers[idx] = { ...libraryState.papers[idx], tags };
}

export function applyFilter(papers: PaperMeta[]): PaperMeta[] {
  const q = libraryState.query.trim().toLowerCase();
  const tags = libraryState.selectedTags;
  const collMembers =
    libraryState.selectedCollection !== null
      ? membersOf(libraryState.selectedCollection)
      : null;
  const filtered = papers.filter((p) => {
    // Collection filter: paper must be a member of the active collection.
    if (collMembers !== null && !collMembers.has(p.citekey)) return false;
    // Tag filter is an intersection: every selected tag must be present.
    if (tags.length > 0 && !tags.every((t) => p.tags.includes(t))) return false;
    if (!q) return true;
    if (p.title.toLowerCase().includes(q)) return true;
    if (p.authors.some((a) => a.toLowerCase().includes(q))) return true;
    if (p.journal && p.journal.toLowerCase().includes(q)) return true;
    if (p.tags.some((t) => t.toLowerCase().includes(q))) return true;
    if (p.citekey.toLowerCase().includes(q)) return true;
    return false;
  });
  return sortPapers(filtered);
}

/** Add a tag to the active filter (or remove if already present). Used by the
 *  clickable tag chips in the note metadata header. */
export function toggleTagFilter(tag: string): void {
  const cur = libraryState.selectedTags;
  libraryState.selectedTags = cur.includes(tag)
    ? cur.filter((t) => t !== tag)
    : [...cur, tag];
}

export function clearTagFilter(): void {
  libraryState.selectedTags = [];
}

/** Active collection filter setter (null clears). */
export function setCollectionFilter(slug: string | null): void {
  libraryState.selectedCollection = slug;
}

/** Probe the embed server once on app start; populates libraryState.embedHealth. */
export async function probeEmbedServer(): Promise<void> {
  try {
    const h = await embedServerHealth();
    libraryState.embedHealth = h;
  } catch (e) {
    libraryState.embedHealth = {
      ok: false,
      default: "",
      registered: [],
      loaded: [],
      uptimeSec: 0,
      idleSec: 0,
      error: String(e),
    };
  }
}

let semanticToken = 0;
let semanticDebounce: number | null = null;
const SEMANTIC_DEBOUNCE_MS = 250;

export function scheduleSemanticSearch(): void {
  if (semanticDebounce !== null) window.clearTimeout(semanticDebounce);
  const q = libraryState.query.trim();
  if (libraryState.searchMode !== "semantic" || !q) {
    libraryState.semanticResults = null;
    libraryState.semanticError = null;
    libraryState.semanticLoading = false;
    libraryState.semanticWarming = false;
    return;
  }
  const myToken = ++semanticToken;
  semanticDebounce = window.setTimeout(async () => {
    semanticDebounce = null;
    libraryState.semanticLoading = true;
    libraryState.semanticError = null;
    // After 500ms, surface a "warming…" indicator so the user knows we're not stuck.
    const warmTimer = window.setTimeout(() => {
      if (semanticToken === myToken && libraryState.semanticLoading) {
        libraryState.semanticWarming = true;
      }
    }, 500);
    try {
      const hits = await searchSemantic(q, 50);
      if (semanticToken !== myToken) return; // stale
      libraryState.semanticResults = hits;
    } catch (e) {
      if (semanticToken !== myToken) return;
      libraryState.semanticError = String(e);
    } finally {
      window.clearTimeout(warmTimer);
      if (semanticToken === myToken) {
        libraryState.semanticLoading = false;
        libraryState.semanticWarming = false;
      }
    }
  }, SEMANTIC_DEBOUNCE_MS);
}

export function setSearchMode(mode: SearchMode): void {
  libraryState.searchMode = mode;
  if (mode === "metadata") {
    libraryState.semanticResults = null;
    libraryState.semanticError = null;
  } else {
    scheduleSemanticSearch();
  }
}

/** When semantic mode is active and we have results, project them onto loaded PaperMeta
 * preserving the rank order. Hits referencing unknown citekeys are dropped silently —
 * the embeddings DB can lag behind the note set. */
export function semanticPapers(): PaperMeta[] {
  const hits = libraryState.semanticResults;
  if (!hits) return [];
  const byKey = new Map(libraryState.papers.map((p) => [p.citekey, p]));
  const out: PaperMeta[] = [];
  for (const h of hits) {
    const p = byKey.get(h.citekey);
    if (p) out.push(p);
  }
  return out;
}

function sortPapers(papers: PaperMeta[]): PaperMeta[] {
  const key = libraryState.sortKey;
  const dir = libraryState.sortDir === "asc" ? 1 : -1;
  // For "opened" we need fast citekey → opened-at lookup.
  let openedAt: Map<string, number> | null = null;
  if (key === "opened") {
    const recents = prefsState.recents;
    openedAt = new Map(recents.map((r) => [r.citekey, r.at]));
  }
  return [...papers].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "added": {
        const ta = parseAddedTimestamp(a.added);
        const tb = parseAddedTimestamp(b.added);
        cmp = ta - tb;
        break;
      }
      case "opened": {
        const ta = openedAt!.get(a.citekey) ?? 0;
        const tb = openedAt!.get(b.citekey) ?? 0;
        cmp = ta - tb;
        break;
      }
      case "year":
        cmp = a.year - b.year;
        break;
      case "title":
        cmp = a.title.localeCompare(b.title);
        break;
      case "journal":
        cmp = (a.journal ?? "").localeCompare(b.journal ?? "");
        break;
    }
    return cmp * dir;
  });
}

/** Parse the frontmatter `added` field. Bare YYYY-MM-DD becomes local-noon
 *  to keep day-resolution sorting stable across timezones. */
export function parseAddedTimestamp(iso: string): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso.trim())) return t + 12 * 60 * 60_000;
  return t;
}

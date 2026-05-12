import {
  listInbox,
  inboxRetryFile,
  inboxDelete,
  searchCrossref,
  inboxFileWithDoi,
  type InboxItem,
  type FilingOutcome,
  type CrossrefCandidate,
} from "../lib/vault";

interface InboxState {
  items: InboxItem[];
  loading: boolean;
  loadError: string | null;
}

export const inboxState = $state<InboxState>({
  items: [],
  loading: false,
  loadError: null,
});

/**
 * One-shot navigation flag set by the reading-view's fold-out when the
 * user clicks the Inbox row. CollectionsPanel's $effect watches this
 * and, when set, switches its right pane to the inbox view and resets
 * the flag. Pairs with `prefsState.collectionsPanelOpen = true` set by
 * the same click so the organize overlay actually opens.
 */
export const inboxNav = $state<{ wantOpen: number }>({ wantOpen: 0 });

export function requestOpenInbox(): void {
  inboxNav.wantOpen++;
}

let inflight: Promise<void> | null = null;

export async function refreshInbox(): Promise<void> {
  if (inflight) return inflight;
  inboxState.loading = true;
  inflight = (async () => {
    try {
      inboxState.items = await listInbox();
      inboxState.loadError = null;
    } catch (e) {
      inboxState.loadError = String(e);
    } finally {
      inboxState.loading = false;
      inflight = null;
    }
  })();
  return inflight;
}

export async function retryFile(path: string): Promise<FilingOutcome> {
  const result = await inboxRetryFile(path);
  // The file moves out of Inbox on success (or duplicate); refresh either way.
  await refreshInbox();
  return result;
}

export async function deleteFromInbox(path: string): Promise<void> {
  await inboxDelete(path);
  await refreshInbox();
}

/** Per-row search state for the Inbox CrossRef assist. Keyed by the
 *  PDF's inbox path. Holds the title/author/year inputs the user is
 *  filling in, the candidate list returned by the most recent search,
 *  and a loading flag. Only the row that's currently expanded for
 *  search has an entry; rows are cleared on filing or collapse. */
interface RowSearchState {
  title: string;
  author: string;
  query: string;
  year: string;
  candidates: CrossrefCandidate[];
  loading: boolean;
  error: string | null;
}

export const searchByPath = $state<Record<string, RowSearchState>>({});

export function openSearchFor(path: string, filename: string): void {
  if (searchByPath[path]) return;
  /* Seed the title field from the filename, sans `.pdf`. Many users
   * name PDFs after the paper title, so this saves a few keystrokes. */
  const seed = filename.replace(/\.pdf$/i, "").replace(/[_-]+/g, " ").trim();
  searchByPath[path] = {
    title: seed,
    author: "",
    query: "",
    year: "",
    candidates: [],
    loading: false,
    error: null,
  };
}

export function closeSearchFor(path: string): void {
  delete searchByPath[path];
}

export async function runSearchFor(path: string): Promise<void> {
  const s = searchByPath[path];
  if (!s) return;
  s.loading = true;
  s.error = null;
  try {
    const year = s.year.trim() ? parseInt(s.year.trim(), 10) : undefined;
    if (year !== undefined && Number.isNaN(year)) {
      s.error = "Year must be a number";
      return;
    }
    const candidates = await searchCrossref({
      title: s.title || undefined,
      author: s.author || undefined,
      query: s.query || undefined,
      year,
    });
    s.candidates = candidates;
    if (candidates.length === 0) s.error = "No matches from CrossRef";
  } catch (e) {
    s.error = String(e);
    s.candidates = [];
  } finally {
    s.loading = false;
  }
}

export async function fileWithDoi(
  path: string,
  doi: string,
): Promise<FilingOutcome> {
  const result = await inboxFileWithDoi(path, doi);
  delete searchByPath[path];
  await refreshInbox();
  return result;
}

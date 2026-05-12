import {
  listCollections,
  collectionAdd as addPaperRpc,
  collectionRemove as removePaperRpc,
  collectionCreate as createRpc,
  collectionDelete as deleteRpc,
  collectionRename as renameRpc,
  type Collection,
} from "../lib/vault";

interface CollectionsState {
  /** Flat list of all collections, sorted by slug — caller derives the tree
   *  structure when needed. */
  list: Collection[];
  loadError: string | null;
  loading: boolean;
}

export const collectionsState = $state<CollectionsState>({
  list: [],
  loadError: null,
  loading: false,
});

let inflight: Promise<void> | null = null;

export async function refreshCollections(): Promise<void> {
  if (inflight) return inflight;
  collectionsState.loading = true;
  inflight = (async () => {
    try {
      collectionsState.list = await listCollections();
      collectionsState.loadError = null;
    } catch (e) {
      collectionsState.loadError = String(e);
    } finally {
      collectionsState.loading = false;
      inflight = null;
    }
  })();
  return inflight;
}

/** Optimistically apply a paper-add and patch the in-memory copy, then
 *  reconcile with the server's reply. */
export async function addPaperToCollection(slug: string, citekey: string): Promise<void> {
  const idx = collectionsState.list.findIndex((c) => c.slug === slug);
  if (idx >= 0 && !collectionsState.list[idx].papers.includes(citekey)) {
    collectionsState.list[idx] = {
      ...collectionsState.list[idx],
      papers: [...collectionsState.list[idx].papers, citekey],
    };
  }
  const updated = await addPaperRpc(slug, citekey);
  if (idx >= 0) collectionsState.list[idx] = updated;
}

export async function removePaperFromCollection(slug: string, citekey: string): Promise<void> {
  const idx = collectionsState.list.findIndex((c) => c.slug === slug);
  if (idx >= 0 && collectionsState.list[idx].papers.includes(citekey)) {
    collectionsState.list[idx] = {
      ...collectionsState.list[idx],
      papers: collectionsState.list[idx].papers.filter((c) => c !== citekey),
    };
  }
  const updated = await removePaperRpc(slug, citekey);
  if (idx >= 0) collectionsState.list[idx] = updated;
}

export async function createCollection(
  slug: string,
  name?: string,
  description?: string,
): Promise<Collection> {
  const c = await createRpc(slug, name, description);
  await refreshCollections();
  return c;
}

export async function deleteCollection(slug: string): Promise<void> {
  await deleteRpc(slug);
  await refreshCollections();
}

export async function renameCollection(oldSlug: string, newSlug: string): Promise<Collection> {
  const c = await renameRpc(oldSlug, newSlug);
  await refreshCollections();
  return c;
}

/** Return the slug → Collection map for fast lookup. */
export function collectionsBySlug(): Map<string, Collection> {
  return new Map(collectionsState.list.map((c) => [c.slug, c]));
}

/** Set of citekeys that belong to the given collection — including
 *  every paper in any descendant collection. The inheritance is
 *  view-only: this function unions members across the subtree but
 *  does not modify the underlying index.md files. Descendants are
 *  identified by slug prefix: a collection with slug `parent/child`
 *  is a descendant of `parent`. */
export function membersOf(slug: string): Set<string> {
  const out = new Set<string>();
  const prefix = slug + "/";
  for (const c of collectionsState.list) {
    if (c.slug === slug || c.slug.startsWith(prefix)) {
      for (const p of c.papers) out.add(p);
    }
  }
  return out;
}

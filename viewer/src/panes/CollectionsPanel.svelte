<script lang="ts">
  /**
   * Organize view — full-window editorial-library takeover for managing
   * collections (Direction B aesthetic). Layout per design pack:
   *
   *   ┌─ 56px top strip ──────────────────────────────────────────────┐
   *   │ traffic-lights · [Reading | ORGANIZING]   The Vault · No. 129 │
   *   ├─ 340px ──────────────┬────────────────────────────────────────┤
   *   │ COLLECTIONS  drag…   │ SOURCE · viewing                       │
   *   │ ▾ all papers   129   │ next paper — interface fracture ▾  13  │
   *   │ ▸ unfiled       43   │ drag rows onto a collection on the     │
   *   │ ▸ projects      71   │ left to copy them there                │
   *   │   ▸ silica…     12   │  Search… [SEM] · show ▾ · Tags · sort  │
   *   │   ▸ next paper   6   │  N SELECTED · drag onto a coll · clear │
   *   │ ▸ archive       55   │  №  TITLE  AUTHORS  JOURNAL  YEAR  IN  │
   *   │                      │  01  …                                  │
   *   │ ┌── + new ──┐        │  02  …                                  │
   *   └──────────────────────┴────────────────────────────────────────┘
   *
   * Interactions per the design's chat: row-as-checkbox (whole row toggles
   * selection), drag any selected row to drag all, drop on a tree node to
   * copy, double-click a row to open it (returns to Reading view).
   */
  import {
    collectionsState,
    addPaperToCollection,
    removePaperFromCollection,
    createCollection,
    deleteCollection,
    renameCollection,
    membersOf,
  } from "../state/collections.svelte";
  import {
    libraryState,
    parseAddedTimestamp,
    setCollectionFilter,
    toggleTagFilter,
    clearTagFilter,
    allTags,
    setSearchMode,
    scheduleSemanticSearch,
    semanticPapers,
  } from "../state/library.svelte";
  import { openInTab } from "../state/tabs.svelte";
  import { prefsState } from "../state/prefs.svelte";
  import { toast } from "../state/toast.svelte";
  import {
    type Collection,
    type PaperMeta,
  } from "../lib/vault";
  import ViewSwitch from "./ViewSwitch.svelte";
  import PDFView from "./PDFView.svelte";
  import NoteEditor from "./NoteEditor.svelte";
  import InboxFindModal from "./InboxFindModal.svelte";
  import { openCtxMenu } from "../state/ctxmenu.svelte";
  import { paperRowMenu } from "../lib/paper-menu";
  import { onMount, onDestroy } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";

  /** Native window-drag from a JS mousedown handler. data-tauri-drag-
   *  region isn't reliably firing in this build (the OS drag-drop
   *  handler under `dragDropEnabled: true` competes for mousedown).
   *  Triggering startDragging() ourselves works around it. Drag any
   *  click on the strip surface or its non-interactive children;
   *  bail when the click landed on the ViewSwitch buttons / the meta
   *  label so those keep working. */
  function onStripMouseDown(e: MouseEvent): void {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest('button, a, input, textarea, [role="button"], [role="tab"]')) {
      return;
    }
    e.preventDefault();
    getCurrentWindow()
      .startDragging()
      .catch((err) => console.error("startDragging (organize strip) failed:", err));
  }
  import {
    dndState,
    startInternalDrag,
    finishInternalDrag,
  } from "../state/dnd.svelte";
  import { organizeState } from "../state/organize.svelte";
  import {
    inboxState,
    inboxNav,
    refreshInbox,
    retryFile,
    deleteFromInbox,
    searchByPath,
    openSearchFor,
    /* closeSearchFor / runSearchFor / fileWithDoi are now driven from
     * InboxFindModal — kept out of this file's imports to avoid noise.
     * fileCandidate (below) is dead code; left for now so this PR is
     * UI-only. */
  } from "../state/inbox.svelte";
  import { ask } from "@tauri-apps/plugin-dialog";
  import { convertFileSrc } from "@tauri-apps/api/core";

  /* ----- folder tree ------------------------------------------------------ */

  interface TreeNode {
    slug: string;
    leafName: string;
    collection: Collection | null;
    children: TreeNode[];
  }

  const tree = $derived.by<TreeNode[]>(() => {
    const bySlug = new Map<string, Collection>();
    for (const c of collectionsState.list) bySlug.set(c.slug, c);
    const allSlugs = new Set<string>();
    for (const c of collectionsState.list) {
      allSlugs.add(c.slug);
      const parts = c.slug.split("/");
      for (let i = 1; i < parts.length; i++) {
        allSlugs.add(parts.slice(0, i).join("/"));
      }
    }
    const nodes = new Map<string, TreeNode>();
    for (const slug of allSlugs) {
      const leafName = slug.split("/").pop() ?? slug;
      nodes.set(slug, {
        slug,
        leafName,
        collection: bySlug.get(slug) ?? null,
        children: [],
      });
    }
    const roots: TreeNode[] = [];
    for (const slug of [...allSlugs].sort()) {
      const node = nodes.get(slug)!;
      const parentSlug = slug.includes("/")
        ? slug.split("/").slice(0, -1).join("/")
        : null;
      if (parentSlug && nodes.has(parentSlug)) {
        nodes.get(parentSlug)!.children.push(node);
      } else {
        roots.push(node);
      }
    }
    return roots;
  });

  let expanded = $state<Set<string>>(organizeState.expanded);
  $effect(() => { organizeState.expanded = expanded; });
  function toggleExpand(slug: string) {
    const next = new Set(expanded);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    expanded = next;
  }

  /** Auto-expand the slug that's currently being filtered, plus all of
   *  its ancestors, so it's visible in the tree without manual digging. */
  $effect(() => {
    const sel = libraryState.selectedCollection;
    if (!sel) return;
    const next = new Set(expanded);
    const parts = sel.split("/");
    for (let i = 1; i <= parts.length; i++) {
      next.add(parts.slice(0, i).join("/"));
    }
    if (next.size !== expanded.size) expanded = next;
  });

  /**
   * View mode controls which "source" the right pane renders. Most of
   * the time it's `papers` (the paper table, driven by
   * libraryState.selectedCollection). When the user clicks the "Inbox"
   * pseudo-row in the tree, we flip to `inbox` — same table-pane
   * column, different content (un-filed PDFs with retry/delete
   * actions). Switching back to any collection (or "all papers")
   * returns to the paper table.
   */
  let viewMode = $state<"papers" | "inbox">(organizeState.viewMode);
  $effect(() => { organizeState.viewMode = viewMode; });

  /* When the user clicks "find" on an Inbox item, instead of expanding an
   * inline form (where the PDF isn't visible) we open a modal with the PDF
   * preview on one side and the CrossRef search/candidates on the other.
   * `findModalFor` holds the Inbox item being identified, or null. */
  let findModalFor = $state<{ path: string; filename: string } | null>(null);
  function openFindModal(path: string, filename: string) {
    openSearchFor(path, filename); // initialise/preserve the per-row state
    findModalFor = { path, filename };
  }
  function closeFindModal() {
    findModalFor = null;
  }

  function selectSource(slug: string | null) {
    viewMode = "papers";
    setCollectionFilter(slug);
    selected = new Set();
    /* If the user is inside a preview when they click a folder, close
     * it so the source they just picked is actually visible. Without
     * this the preview would stay floating over the table even though
     * the underlying source changed — confusing. */
    previewCitekey = null;
  }

  function selectInbox() {
    viewMode = "inbox";
    setCollectionFilter(null);
    selected = new Set();
    previewCitekey = null;
    void refreshInbox();
  }

  /* React to reading-view fold-out clicks on "Inbox": the fold-out opens
   * this panel via prefsState.collectionsPanelOpen and bumps
   * inboxNav.wantOpen. Auto-switch to the inbox view so the user ends
   * up looking at the right pane without an extra click. */
  let lastInboxNavSeen = $state(0);
  $effect(() => {
    if (inboxNav.wantOpen !== lastInboxNavSeen) {
      lastInboxNavSeen = inboxNav.wantOpen;
      if (inboxNav.wantOpen > 0) selectInbox();
    }
  });

  function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function retryFileWithToast(path: string, filename: string): Promise<void> {
    try {
      const result = await retryFile(path);
      if (result.status === "filed") toast(`Filed → ${result.citekey}`);
      else if (result.status === "duplicate")
        toast(`Already in vault as ${result.citekey ?? "(unknown)"}`, "error");
      else if (result.status === "no-identifier") {
        /* DOI / arXiv extraction failed — open the CrossRef search
         * form right on this row so the user can supply hints. */
        toast("No DOI found — try the CrossRef search below.", "error");
        openSearchFor(path, filename);
      } else if (result.status === "scripts-missing")
        toast("Vault is missing filing scripts (scripts/file_paper.py).", "error");
      else toast(`Filing failed: ${result.detail ?? "unknown error"}`, "error");
    } catch (e) {
      toast(`Retry failed: ${e}`, "error");
    }
  }

  /* fileCandidate moved into InboxFindModal — it owns the candidate-pick
   * → fileWithDoi → toast flow now. */

  async function deleteInboxItem(path: string, filename: string): Promise<void> {
    /* Tauri's WKWebView doesn't always render window.confirm() reliably
     * — the prompt could land silently or be skipped entirely. The
     * dialog plugin's ask() always shows a native modal. */
    const ok = await ask(`Delete "${filename}" from the Inbox? This can't be undone.`, {
      title: "Delete from Inbox",
      kind: "warning",
    });
    if (!ok) return;
    try {
      await deleteFromInbox(path);
      toast(`Deleted ${filename}`);
    } catch (e) {
      toast(`Delete failed: ${e}`, "error");
    }
  }

  /** Remove a paper from the active collection. Called from the
   *  hover-revealed × in the in-col cell when viewing a collection. */
  async function removeFromActive(citekey: string): Promise<void> {
    if (!activeCollection) return;
    try {
      await removePaperFromCollection(activeCollection.slug, citekey);
    } catch (e) {
      toast(`Remove failed: ${e}`, "error");
    }
  }

  /* Refresh the inbox list whenever the library changes (a successful
   * file_paper.py run pulls the PDF out of Inbox and into PaperNotes —
   * the inbox view should reflect that immediately). Also refresh on
   * first mount so the badge count is accurate when the user opens
   * the organize view. */
  onMount(() => {
    void refreshInbox();
  });
  let unlistenInbox: (() => void) | null = null;
  onMount(async () => {
    const { listen } = await import("@tauri-apps/api/event");
    unlistenInbox = await listen("library:changed", () => {
      void refreshInbox();
    });
  });
  onDestroy(() => {
    unlistenInbox?.();
  });

  const activeCollection = $derived.by(() =>
    libraryState.selectedCollection
      ? (collectionsState.list.find(
          (c) => c.slug === libraryState.selectedCollection,
        ) ?? null)
      : null,
  );

  /* ----- papers table source --------------------------------------------- */

  type SortKey = "title" | "author" | "journal" | "year" | "added";
  let sortBy = $state<SortKey>(organizeState.sortBy);
  let sortDir = $state<"asc" | "desc">(organizeState.sortDir);
  $effect(() => { organizeState.sortBy = sortBy; });
  $effect(() => { organizeState.sortDir = sortDir; });

  function toggleSort(k: SortKey) {
    if (sortBy === k) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortBy = k;
      sortDir = k === "year" || k === "added" ? "desc" : "asc";
    }
  }

  function firstAuthorLast(p: PaperMeta): string {
    return (p.authors[0] ?? "").split(",")[0].trim().toLowerCase();
  }

  /** AUTHORS column label — first-author last name + " et al." when the
   *  paper has multiple authors. The YEAR has its own column, so unlike
   *  the reading-view's `paperLabel` we deliberately leave it out here.
   *  authorCount is set when the frontmatter authors list was truncated
   *  to a sentinel "…and N others" by the agent's filing pipeline. */
  function authorsCellLabel(p: PaperMeta): string {
    const first = (p.authors[0] ?? "").split(",")[0].trim();
    const total = p.authorCount ?? p.authors.length;
    if (!first) return "—";
    return total > 1 ? `${first} et al.` : first;
  }

  /** Search is shared with the reading view — typing in organize-mode
   *  fills the reading-view search and vice-versa, so a query carried
   *  over from one mode to the other feels intentional. The semantic
   *  backend is re-fired on every change when in SEM mode. */
  function setQuery(v: string) {
    libraryState.query = v;
    if (libraryState.searchMode === "semantic") scheduleSemanticSearch();
  }
  function clearQuery() {
    setQuery("");
  }
  function toggleSemanticMode() {
    setSearchMode(
      libraryState.searchMode === "semantic" ? "metadata" : "semantic",
    );
  }
  /** Whether the right-side table should rank by semantic similarity:
   *  SEM mode + non-empty query + embed server reachable. Falls back to
   *  substring matching if any of those preconditions miss. */
  const semanticActive = $derived(
    libraryState.searchMode === "semantic"
      && libraryState.query.trim().length > 0
      && (libraryState.embedHealth?.ok ?? false),
  );
  const semanticAvailable = $derived(libraryState.embedHealth?.ok ?? false);

  /** Membership counts: how many collections each citekey appears in.
   *  Used by the IN column on each row. */
  const inCount = $derived.by<Map<string, number>>(() => {
    const m = new Map<string, number>();
    for (const c of collectionsState.list) {
      for (const ck of c.papers) m.set(ck, (m.get(ck) ?? 0) + 1);
    }
    return m;
  });

  /** Hard filters: source collection (or all papers) ∩ selected tags. The
   *  search query is applied as a SOFT filter further below (matched vs
   *  hidden partition) so the user can still see what's been pushed out
   *  of view by their query. */
  const listedPapers = $derived.by<PaperMeta[]>(() => {
    const all = libraryState.papers;
    let pool: PaperMeta[];
    if (activeCollection) {
      const wanted = new Set(activeCollection.papers);
      pool = all.filter((p) => wanted.has(p.citekey));
    } else {
      pool = [...all];
    }
    if (libraryState.selectedTags.length > 0) {
      pool = pool.filter((p) =>
        libraryState.selectedTags.every((t) => p.tags.includes(t)),
      );
    }
    const dir = sortDir === "asc" ? 1 : -1;
    pool.sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "title":
          cmp = a.title.localeCompare(b.title);
          break;
        case "author":
          cmp = firstAuthorLast(a).localeCompare(firstAuthorLast(b));
          break;
        case "journal":
          cmp = (a.journal ?? "").localeCompare(b.journal ?? "");
          break;
        case "year":
          cmp = a.year - b.year;
          break;
        case "added":
          cmp = parseAddedTimestamp(a.added) - parseAddedTimestamp(b.added);
          break;
      }
      return cmp * dir;
    });
    return pool;
  });

  const orphanCitekeys = $derived.by<string[]>(() => {
    if (!activeCollection) return [];
    const have = new Set(libraryState.papers.map((p) => p.citekey));
    return activeCollection.papers.filter((c) => !have.has(c));
  });

  /* ----- search-as-loose-filter — partition matched / hidden -------------
   * Per the design, the right-side search is a soft filter: matched rows
   * surface to the top, the rest tuck below an editorial divider that
   * announces "+N hidden by filter · show all ↓". Tag and source are still
   * hard filters (rows not in the source collection / not tagged are
   * dropped completely). */

  let showAllHidden = $state(organizeState.showAllHidden);
  $effect(() => { organizeState.showAllHidden = showAllHidden; });

  function matchesQuery(p: PaperMeta, q: string): boolean {
    if (!q) return true;
    if (p.title.toLowerCase().includes(q)) return true;
    if (p.authors.some((a) => a.toLowerCase().includes(q))) return true;
    if ((p.journal ?? "").toLowerCase().includes(q)) return true;
    if (String(p.year).includes(q)) return true;
    return false;
  }

  /** Matched rows surface above the divider. In semantic mode the rank
   *  order comes from the embeddings backend (semanticPapers projects
   *  hits onto the loaded library) and is intersected with the source
   *  pool — papers not in the active source are hidden, papers in the
   *  source but not ranked are pushed below the divider. */
  const matchedPapers = $derived.by<PaperMeta[]>(() => {
    if (semanticActive) {
      const ranked = semanticPapers();
      const inPool = new Set(listedPapers.map((p) => p.citekey));
      return ranked.filter((p) => inPool.has(p.citekey));
    }
    const q = libraryState.query.trim().toLowerCase();
    if (!q) return listedPapers;
    return listedPapers.filter((p) => matchesQuery(p, q));
  });
  const hiddenPapers = $derived.by<PaperMeta[]>(() => {
    if (semanticActive) {
      const matched = new Set(matchedPapers.map((p) => p.citekey));
      return listedPapers.filter((p) => !matched.has(p.citekey));
    }
    const q = libraryState.query.trim().toLowerCase();
    if (!q) return [];
    return listedPapers.filter((p) => !matchesQuery(p, q));
  });

  /* ----- multi-select & drag-from-table ---------------------------------- */

  let selected = $state<Set<string>>(organizeState.selected);
  $effect(() => { organizeState.selected = selected; });

  function toggleSelected(citekey: string) {
    const next = new Set(selected);
    if (next.has(citekey)) next.delete(citekey);
    else next.add(citekey);
    selected = next;
  }
  function clearSelected() {
    selected = new Set();
  }

  /** Citekeys for every row currently rendered in the table — matched
   *  rows plus the hidden ones when the user has expanded "show all".
   *  Orphan citekeys are excluded since they don't correspond to loaded
   *  papers; selecting them would be inert. */
  const visibleCitekeys = $derived.by<string[]>(() => {
    const out = matchedPapers.map((p) => p.citekey);
    if (showAllHidden) {
      for (const p of hiddenPapers) out.push(p.citekey);
    }
    return out;
  });
  const allVisibleSelected = $derived(
    visibleCitekeys.length > 0
      && visibleCitekeys.every((ck) => selected.has(ck)),
  );
  function selectAllVisible() {
    selected = new Set(visibleCitekeys);
  }
  /** Header-checkbox click: if everything visible is already selected,
   *  clear; otherwise select all visible. Mirrors the convention used in
   *  most table UIs (Mendeley, Finder, mail clients). */
  function toggleSelectAll() {
    if (allVisibleSelected) clearSelected();
    else selectAllVisible();
  }

  /** When the source collection changes (via tree click or "show" picker),
   *  drop any selection that's no longer in the visible pool. */
  $effect(() => {
    const visible = new Set(listedPapers.map((p) => p.citekey));
    let changed = false;
    const next = new Set<string>();
    for (const ck of selected) {
      if (visible.has(ck)) next.add(ck);
      else changed = true;
    }
    if (changed) selected = next;
  });

  function openPaperAndCollapse(citekey: string) {
    openInTab(citekey);
    prefsState.viewMode = "reading";
  }

  /* ----- drag-drop onto tree nodes --------------------------------------- */

  let dropTargetSlug = $state<string | null>(null);

  /** Drag-row count tracked locally so we can render a "+N" badge inline
   *  on hovered tree nodes. dataTransfer.getData() is restricted in the
   *  dragover phase (security: only accessible on drop), so we mirror the
   *  payload size in module state at dragstart. */
  let dragCount = $state(0);

  function rowsForDrag(citekey: string): string[] {
    return selected.has(citekey) && selected.size > 0
      ? [...selected]
      : [citekey];
  }

  /** Build the off-screen 3-card stack with a "+N" badge. The browser
   *  snapshots it immediately for setDragImage, so we can remove the
   *  element on the next tick. The look mirrors the design pack's drag
   *  ghost: editorial card, burnt-umber left rule, faint rotation, badge
   *  in the corner when more than one row is being dragged. */
  function buildDragGhost(papers: PaperMeta[]): HTMLElement {
    const container = document.createElement("div");
    container.style.cssText = [
      "position:absolute",
      "left:-1000px",
      "top:0",
      "width:340px",
      "height:90px",
      "pointer-events:none",
      "z-index:9999",
      "font-family:Inter, system-ui, sans-serif",
    ].join(";");

    const inner = document.createElement("div");
    inner.style.cssText = "position:relative;width:320px;height:70px";

    const cards = papers.slice(0, Math.min(3, papers.length));
    // Render in reverse so card index 0 ends up on top.
    [...cards].reverse().forEach((p, idx) => {
      const offset = (cards.length - 1 - idx) * 5;
      const rotate = (cards.length - 1 - idx - 1) * -1.5;
      const card = document.createElement("div");
      card.style.cssText = [
        "position:absolute",
        `left:${offset}px`,
        `top:${offset}px`,
        "width:320px",
        "padding:8px 12px",
        "background:#ffffff",
        "border:1px solid #7a3a14",
        "border-left:3px solid #7a3a14",
        `transform:rotate(${rotate}deg)`,
        "box-shadow:0 8px 22px rgba(26,22,18,0.18)",
        "box-sizing:border-box",
      ].join(";");
      const last = (p.authors[0] ?? "").split(",")[0].trim();
      const byline = document.createElement("div");
      byline.style.cssText =
        "font-size:9.5px;color:rgba(26,22,18,0.7);font-weight:600;margin-bottom:2px";
      byline.textContent = `${last} · ${p.year}`;
      const title = document.createElement("div");
      title.style.cssText = [
        'font-family:"Source Serif 4", serif',
        "font-size:12.5px",
        "font-weight:600",
        "color:#1a1612",
        "letter-spacing:-0.2px",
        "line-height:1.25",
        "overflow:hidden",
        "text-overflow:ellipsis",
        "white-space:nowrap",
      ].join(";");
      title.textContent = p.title;
      card.appendChild(byline);
      card.appendChild(title);
      inner.appendChild(card);
    });

    if (papers.length > 1) {
      const badge = document.createElement("div");
      badge.style.cssText = [
        "position:absolute",
        "top:-10px",
        "right:4px",
        "width:30px",
        "height:30px",
        "border-radius:50%",
        "background:#7a3a14",
        "color:#ffffff",
        'font-family:"JetBrains Mono", monospace',
        "font-size:11px",
        "font-weight:700",
        "display:inline-flex",
        "align-items:center",
        "justify-content:center",
        "box-shadow:0 2px 6px rgba(122,58,20,0.5)",
      ].join(";");
      badge.textContent = `+${papers.length}`;
      inner.appendChild(badge);
    }

    container.appendChild(inner);
    document.body.appendChild(container);
    queueMicrotask(() => container.remove());
    return container;
  }

  function setDragData(e: DragEvent, ckList: string[]) {
    if (!e.dataTransfer) return;
    e.dataTransfer.setData("application/x-vault-citekey", ckList[0] ?? "");
    e.dataTransfer.setData("application/x-vault-citekeys", ckList.join("\n"));
    e.dataTransfer.setData("text/plain", ckList.join("\n"));
    e.dataTransfer.effectAllowed = "copy";
    dragCount = ckList.length;
    /* WKWebView swallows our HTML5 ondragover/ondrop on tree nodes, so
     * the actual drop is routed through Tauri's OS handler in
     * App.svelte. Record the citekeys here; App reads them on drop. */
    startInternalDrag(ckList);
  }
  /** Called on HTML5 dragend on a draggable row. Executes the actual
   *  collection-add via finishInternalDrag, which reads dndState
   *  (citekeys + hover slug Tauri tracked during over events) and
   *  fans out to addPaperToCollection. */
  function endDrag(e?: DragEvent) {
    dragCount = 0;
    dropTargetSlug = null;
    void finishInternalDrag(e);
  }
  async function onDropOnNode(
    e: DragEvent,
    slug: string,
    isCollection: boolean,
  ) {
    e.preventDefault();
    dropTargetSlug = null;
    if (!isCollection) {
      toast("Can't drop into a container — only into a collection.", "error");
      return;
    }
    const multi = e.dataTransfer?.getData("application/x-vault-citekeys");
    const single = e.dataTransfer?.getData("application/x-vault-citekey")
      || e.dataTransfer?.getData("text/plain");
    const ckList = multi ? multi.split("\n").filter(Boolean) : (single ? [single] : []);
    if (ckList.length === 0) return;
    let ok = 0;
    let fail: string[] = [];
    for (const ck of ckList) {
      try {
        await addPaperToCollection(slug, ck);
        ok++;
      } catch (err) {
        fail.push(`${ck}: ${err}`);
      }
    }
    if (fail.length === 0) toast(`Added ${ok} → ${slug}`);
    else toast(`Added ${ok}, failed ${fail.length}`, "error");
  }

  /* ----- create / rename / delete ---------------------------------------- */

  let creating = $state(false);
  let newSlug = $state("");
  let creatingParent = $state<string | null>(null);
  let createInput = $state<HTMLInputElement | null>(null);

  function openCreate(parentSlug: string | null) {
    creating = true;
    creatingParent = parentSlug;
    newSlug = "";
    if (parentSlug && !expanded.has(parentSlug)) {
      const next = new Set(expanded);
      next.add(parentSlug);
      expanded = next;
    }
    queueMicrotask(() => createInput?.focus());
  }
  function cancelCreate() {
    creating = false;
    newSlug = "";
    creatingParent = null;
  }
  async function commitCreate() {
    const leaf = newSlug.trim();
    if (!leaf) {
      cancelCreate();
      return;
    }
    const fullSlug = creatingParent ? `${creatingParent}/${leaf}` : leaf;
    try {
      await createCollection(fullSlug);
      toast(`Created ${fullSlug}`);
      cancelCreate();
    } catch (e) {
      toast(`Create failed: ${e}`, "error");
    }
  }

  let renamingSlug = $state<string | null>(null);
  let renameInput = $state<HTMLInputElement | null>(null);
  let renameValue = $state("");
  function startRename(slug: string) {
    renamingSlug = slug;
    renameValue = slug.split("/").pop() ?? slug;
    queueMicrotask(() => {
      renameInput?.focus();
      renameInput?.select();
    });
  }
  function cancelRename() {
    renamingSlug = null;
    renameValue = "";
  }
  async function commitRename() {
    if (!renamingSlug) return;
    const leaf = renameValue.trim();
    if (!leaf) {
      cancelRename();
      return;
    }
    const parts = renamingSlug.split("/");
    parts[parts.length - 1] = leaf;
    const newFullSlug = parts.join("/");
    if (newFullSlug === renamingSlug) {
      cancelRename();
      return;
    }
    try {
      await renameCollection(renamingSlug, newFullSlug);
      toast(`Renamed to ${newFullSlug}`);
      if (libraryState.selectedCollection === renamingSlug) {
        setCollectionFilter(newFullSlug);
      }
      cancelRename();
    } catch (e) {
      toast(`Rename failed: ${e}`, "error");
    }
  }

  async function confirmDelete(slug: string, memberCount: number) {
    const msg =
      memberCount > 0
        ? `Delete collection "${slug}" with ${memberCount} paper${memberCount === 1 ? "" : "s"}? The papers themselves stay in the library.`
        : `Delete collection "${slug}"?`;
    const ok = await ask(msg, { title: "Delete collection", kind: "warning" });
    if (!ok) return;
    try {
      await deleteCollection(slug);
      if (libraryState.selectedCollection === slug) setCollectionFilter(null);
      toast(`Deleted ${slug}`);
    } catch (e) {
      toast(`Delete failed: ${e}`, "error");
    }
  }

  function shortAdded(iso: string): string {
    const t = parseAddedTimestamp(iso);
    if (!t) return "—";
    return new Date(t).toISOString().slice(0, 10);
  }

  /* "show ▾" source picker — lightweight popover. The active source name
   *  doubles as the picker trigger. */
  let sourceMenuOpen = $state(false);
  function pickSource(slug: string | null) {
    selectSource(slug);
    sourceMenuOpen = false;
  }

  /* ----- preview pane ---------------------------------------------------- */
  /* Double-clicking a row floats the paper (PDF + notes) on top of the
   * library table with a glass-blur scrim — leaves the collections tree
   * on the left untouched, per the design pack. The library + reader
   * underneath the organize overlay stay mounted regardless, so closing
   * the preview returns to the table without re-fetching anything. */

  let previewCitekey = $state<string | null>(organizeState.previewCitekey);
  $effect(() => { organizeState.previewCitekey = previewCitekey; });
  /** Path of an Inbox PDF being previewed. Mutually exclusive with
   *  previewCitekey — the preview overlay branches on which one is
   *  set: paper preview (PDF + notes, library row) vs inbox preview
   *  (just the PDF, with a "file this paper" affordance). */
  let previewInboxPath = $state<string | null>(organizeState.previewInboxPath);
  $effect(() => { organizeState.previewInboxPath = previewInboxPath; });
  let previewInboxFilename = $state<string>("");

  function previewPaper(citekey: string) {
    previewInboxPath = null;
    previewCitekey = citekey;
  }
  function previewInboxItem(path: string, filename: string) {
    previewCitekey = null;
    previewInboxPath = path;
    previewInboxFilename = filename;
  }
  function closePreview() {
    previewCitekey = null;
    previewInboxPath = null;
    previewInboxFilename = "";
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      if (previewCitekey || previewInboxPath) {
        e.preventDefault();
        closePreview();
      } else if (sourceMenuOpen) {
        sourceMenuOpen = false;
      }
      return;
    }
    /* ⌘A / ⌃A — select all visible rows in the source. Skipped when
     * the user is typing in an input/textarea so the system default
     * (select all text) still works in those fields. */
    if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey
        && (e.key === "a" || e.key === "A")) {
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || t?.isContentEditable) return;
      e.preventDefault();
      if (allVisibleSelected) clearSelected();
      else selectAllVisible();
    }
  }
  onMount(() => window.addEventListener("keydown", onKeyDown));
  onDestroy(() => window.removeEventListener("keydown", onKeyDown));

  /* ----- tag chips ------------------------------------------------------- */
  /* Same vocabulary as the reading view's chips: a single-row strip
   * (horizontal scroll by default, multi-row when expanded). The active
   * set is shared with `libraryState.selectedTags` so chip-clicks are
   * consistent across views. */
  let tagsExpanded = $state(organizeState.tagsExpanded);
  $effect(() => { organizeState.tagsExpanded = tagsExpanded; });
  const visibleTags = $derived(allTags());
</script>

<section class="organize">
  <!-- 56px top strip — same shape as Library's. The ViewSwitch lives at
       the same screen (x, y) so flipping back to Reading doesn't move
       the cursor. Window drag wired explicitly via onStripMouseDown. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="top-strip"
    data-tauri-drag-region
    onmousedown={onStripMouseDown}>
    <ViewSwitch active="organize" />
    <div class="strip-spacer"></div>
    <span class="top-meta">
      {libraryState.papers.length} papers · {collectionsState.list.length} collections
    </span>
  </div>

  <div class="columns">
    <!-- Folders / collections tree --------------------------------------- -->
    <aside class="folders-pane">
      <div class="pane-head">
        <div class="caps">Collections</div>
        <span class="hint">drag here to add</span>
      </div>

      <div class="tree-scroll">
        <button
          class="tree-row all-row"
          class:active={viewMode === "papers" && !libraryState.selectedCollection}
          onclick={() => selectSource(null)}>
          <span class="caret-spacer"></span>
          <span class="leaf-icon mono">∀</span>
          <span class="leaf-name">all papers</span>
          <span class="leaf-count">{libraryState.papers.length}</span>
        </button>

        <!-- Inbox pseudo-row — shows PDFs that haven't been filed into
             the library yet (no DOI extracted, scripts missing, or
             duplicate of an existing paper). Click to inspect them on
             the right; retry filing or delete. The count badge nudges
             the user toward cleaning up. -->
        <button
          class="tree-row all-row inbox-row"
          class:active={viewMode === "inbox"}
          class:has-items={inboxState.items.length > 0}
          onclick={selectInbox}>
          <span class="caret-spacer"></span>
          <span class="leaf-icon mono">⌬</span>
          <span class="leaf-name">inbox</span>
          <span class="leaf-count">{inboxState.items.length}</span>
        </button>

        {#if creating && creatingParent === null}
          <div class="create-row" style="--depth: 0;">
            <input
              bind:this={createInput}
              bind:value={newSlug}
              class="create-input"
              placeholder="new-collection-slug"
              onkeydown={(e) => {
                if (e.key === "Enter") void commitCreate();
                else if (e.key === "Escape") cancelCreate();
              }}
              onblur={() => { if (newSlug.trim()) void commitCreate(); else cancelCreate(); }} />
          </div>
        {/if}

        {#each tree as node (node.slug)}
          {@render TreeNode(node, 0)}
        {/each}

        <div class="tree-bottom-pad"></div>
      </div>

      <!-- "+ new collection" — dashed editorial affordance fixed at bottom -->
      <button class="new-coll" onclick={() => openCreate(null)}>
        <span class="plus">+</span>
        <span class="label">new collection…</span>
      </button>
    </aside>

    {#snippet TreeNode(node: TreeNode, depth: number)}
      {@const isOpen = expanded.has(node.slug)}
      {@const isActive = libraryState.selectedCollection === node.slug}
      {@const memberCount = node.collection ? membersOf(node.collection.slug).size : 0}
      <!-- The data-drop-target-slug attribute opts this node into the
           Tauri-routed drop handler in App.svelte. The HTML5 ondragover
           / ondrop handlers are kept as a fallback for runtimes where
           WKWebView's interception doesn't apply, but the live path on
           macOS Tauri is the OS handler reading this attribute. -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="tree-row-wrap"
        class:active={isActive}
        class:container={!node.collection}
        class:drop-target={node.collection && (dropTargetSlug === node.slug || dndState.hoverSlug === node.slug)}
        style="--depth: {depth};"
        data-drop-target-slug={node.collection ? node.slug : null}
        ondragover={(e) => {
          if (!node.collection) return;
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
          dropTargetSlug = node.slug;
        }}
        ondragleave={() => {
          if (dropTargetSlug === node.slug) dropTargetSlug = null;
        }}
        ondrop={(e) => onDropOnNode(e, node.slug, !!node.collection)}
      >
        <button
          class="caret"
          class:invisible={node.children.length === 0}
          onclick={() => toggleExpand(node.slug)}
          aria-label={isOpen ? "Collapse" : "Expand"}>▾</button>
        {#if renamingSlug === node.slug}
          <input
            bind:this={renameInput}
            bind:value={renameValue}
            class="rename-input"
            onkeydown={(e) => {
              if (e.key === "Enter") void commitRename();
              else if (e.key === "Escape") cancelRename();
            }}
            onblur={() => { if (renameValue.trim()) void commitRename(); else cancelRename(); }} />
        {:else}
          <button
            class="leaf-btn"
            onclick={() => node.collection && selectSource(node.slug)}
            ondblclick={() => node.collection && startRename(node.slug)}
            disabled={!node.collection}
            title={node.collection ? `${node.slug} — double-click to rename` : node.slug}
          >
            <span class="leaf-icon serif">{node.collection ? "/" : "◆"}</span>
            <span class="leaf-name" class:group-name={!node.collection}>
              {node.leafName}
            </span>
            {#if node.collection && (dndState.hoverSlug === node.slug || dropTargetSlug === node.slug) && (dndState.citekeys.length > 0 || dragCount > 0)}
              <span class="drop-count mono">+{dndState.citekeys.length || dragCount}</span>
            {:else}
              <span class="leaf-count">{memberCount}</span>
            {/if}
          </button>
          <div class="row-actions">
            <button
              class="row-btn"
              onclick={() => openCreate(node.slug)}
              title={`New collection inside ${node.slug}`}
              aria-label="New child collection">+</button>
            {#if node.collection}
              <button
                class="row-btn"
                onclick={() => confirmDelete(node.slug, memberCount)}
                title={`Delete ${node.slug}`}
                aria-label="Delete collection">×</button>
            {/if}
          </div>
        {/if}
      </div>
      {#if creating && creatingParent === node.slug}
        <div class="create-row" style="--depth: {depth + 1};">
          <input
            bind:this={createInput}
            bind:value={newSlug}
            class="create-input"
            placeholder="new-child-slug"
            onkeydown={(e) => {
              if (e.key === "Enter") void commitCreate();
              else if (e.key === "Escape") cancelCreate();
            }}
            onblur={() => { if (newSlug.trim()) void commitCreate(); else cancelCreate(); }} />
        </div>
      {/if}
      {#if isOpen}
        {#each node.children as child (child.slug)}
          {@render TreeNode(child, depth + 1)}
        {/each}
      {/if}
    {/snippet}

    {#snippet InboxView()}
      <div class="masthead">
        <div class="caps eyebrow">Awaiting filing</div>
        <div class="title-row">
          <span class="source-name">inbox</span>
          <span class="paper-count">
            {inboxState.items.length} file{inboxState.items.length === 1 ? "" : "s"}
          </span>
        </div>
        <div class="masthead-helper">
          PDFs that haven't been filed yet — usually because no DOI or
          arXiv ID could be extracted, or the vault's filing scripts
          aren't installed. Drop more PDFs here, or use Retry once
          you've fixed the cause.
        </div>
      </div>

      {#if inboxState.items.length === 0}
        <div class="empty-table">
          <p>Inbox is empty.</p>
          <p class="hint">Drop a PDF onto the window or hit ⌘N to add one.</p>
        </div>
      {:else}
        <div class="thead inbox-thead" role="row">
          <div class="th idx-col mono">№</div>
          <div class="th title-col">filename</div>
          <div class="th journal-col">added</div>
          <div class="th year-col">size</div>
          <div class="th in-col">actions</div>
        </div>
        <ul class="tbody" role="rowgroup">
          {#each inboxState.items as item, i (item.path)}
            {@const search = searchByPath[item.path]}
            <li role="row" class="inbox-li">
              <div class="row inbox-row-grid">
                <span class="td idx-col mono">{String(i + 1).padStart(2, "0")}</span>
                <button
                  class="td title-col inbox-filename-btn"
                  title={`Preview: ${item.path}`}
                  onclick={() => previewInboxItem(item.path, item.filename)}>{item.filename}</button>
                <span class="td journal-col mono">{item.modifiedAt.slice(0, 10)}</span>
                <span class="td year-col mono">{formatBytes(item.sizeBytes)}</span>
                <span class="td in-col inbox-actions">
                  <button
                    class="inbox-action"
                    onclick={() => retryFileWithToast(item.path, item.filename)}
                    title="Re-run the auto-filing pipeline on this PDF">retry</button>
                  <button
                    class="inbox-action"
                    class:active={findModalFor?.path === item.path}
                    onclick={() => openFindModal(item.path, item.filename)}
                    title="Identify this PDF (CrossRef search with preview)">find</button>
                  <button
                    class="inbox-action danger"
                    onclick={() => deleteInboxItem(item.path, item.filename)}
                    title="Remove this PDF from the Inbox (permanent)">×</button>
                </span>
              </div>

              <!-- CrossRef search form now lives in InboxFindModal —
                   keeping a tiny inline error/loading sliver here so the user
                   can see search activity initiated from the modal without
                   keeping the modal open. -->
              {#if search && (search.loading || search.error)}
                <div class="inbox-search">
                  {#if search.loading}
                    <div class="inbox-search-error" style="color: var(--ink-50);">Searching CrossRef…</div>
                  {/if}
                  {#if search.error}
                    <div class="inbox-search-error">{search.error}</div>
                  {/if}
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {/snippet}

    <!-- Right pane — paper table when viewMode === "papers", Inbox
         view when viewMode === "inbox". Wrapping both in one
         <section> keeps the grid columns shared. -->
    <section class="table-pane">
      {#if viewMode === "inbox"}
        {@render InboxView()}
      {:else}
      <!-- Masthead — eyebrow, big collection name (also the Source picker
           trigger), helper italic line. -->
      <div class="masthead">
        <div class="caps eyebrow">Source · viewing</div>
        <div class="title-row">
          <button class="source-trigger" onclick={() => (sourceMenuOpen = !sourceMenuOpen)}>
            <span class="source-name">
              {activeCollection ? activeCollection.slug : "all papers"}
            </span>
            <span class="chev">▾</span>
          </button>
          <span class="paper-count">{listedPapers.length} papers</span>
        </div>
        <div class="masthead-helper">
          drag rows onto a collection on the left to copy them there
        </div>
        {#if activeCollection?.description}
          <div class="active-description">{activeCollection.description}</div>
        {/if}

        {#if sourceMenuOpen}
          <ul class="source-menu" role="menu">
            <li>
              <button onclick={() => pickSource(null)} class:on={!activeCollection}>
                <span class="m-icon">∀</span>
                <span class="m-name">all papers</span>
                <span class="m-count">{libraryState.papers.length}</span>
              </button>
            </li>
            {#each collectionsState.list as c (c.slug)}
              <li>
                <button onclick={() => pickSource(c.slug)} class:on={activeCollection?.slug === c.slug}>
                  <span class="m-icon">/</span>
                  <span class="m-name">{c.slug}</span>
                  <span class="m-count">{c.papers.length}</span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- Toolbar — search input + tag chips + sort caption -->
      <div class="toolbar">
        <div class="search-row">
          <span class="search-icon" aria-hidden="true">
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="5.5" cy="5.5" r="4" />
              <path d="M8.5 8.5l3 3" stroke-linecap="round" />
            </svg>
          </span>
          <input
            type="search"
            placeholder={libraryState.searchMode === "semantic"
              ? "Describe what you're looking for…"
              : "Search this source…"}
            value={libraryState.query}
            oninput={(e) => setQuery((e.target as HTMLInputElement).value)} />
          <!-- SEM mode toggle — same vocabulary as the reading view's
               toggle. Disabled when the embed server can't be reached;
               while it's warming up we surface "warming…" so the user
               knows we haven't given up. -->
          <button
            class="sem-toggle"
            class:on={libraryState.searchMode === "semantic"}
            disabled={!semanticAvailable}
            onclick={toggleSemanticMode}
            title={semanticAvailable
              ? `Semantic search ${libraryState.searchMode === "semantic" ? "(on — click for substring)" : "(off — click for embeddings)"}`
              : "Semantic search unavailable — embed server not reachable"}>
            {libraryState.semanticWarming ? "…" : "SEM"}
          </button>
          {#if libraryState.query}
            <button class="clear-q" onclick={clearQuery} title="Clear">×</button>
          {/if}
        </div>

        <!-- Tag chips — same vocabulary as the reading view, shared state.
             Single row by default with horizontal scroll; click "Tags" to
             expand into a multi-row block. Active chips render filled
             black per Direction B; inactive are hairline outlines. -->
        {#if visibleTags.length > 0}
          <div class="tag-strip" class:expanded={tagsExpanded}>
            <button
              class="tag-toggle"
              onclick={() => (tagsExpanded = !tagsExpanded)}
              title="Tags · click to expand">
              Tags {tagsExpanded ? "▴" : "▾"}
            </button>
            <div class="chips">
              {#each visibleTags as t (t)}
                <button
                  class="chip"
                  class:on={libraryState.selectedTags.includes(t)}
                  class:cite={t.startsWith("cite:")}
                  onclick={() => toggleTagFilter(t)}
                  title={`Toggle "${t}" as filter`}>{t.replace(/^cite:/, "")}</button>
              {/each}
              {#if libraryState.selectedTags.length > 0}
                <button class="chip-clear" onclick={() => clearTagFilter()}>clear</button>
              {/if}
            </div>
          </div>
        {/if}

        <div class="toolbar-spacer"></div>
        <span class="sort-caption">
          sort · {sortBy} <span class="dir">{sortDir === "asc" ? "↑" : "↓"}</span>
        </span>
      </div>

      <!-- Header row -->
      <div class="thead" role="row">
        <!-- Header cb-col is a select-all checkbox. Three states:
             - 0 selected         → empty square; click selects all visible
             - some selected      → small accent count chip; click clears
             - all visible selected → filled checkbox; click clears
             Also reachable via ⌘A while focus is outside an input. -->
        <button
          class="th cb-col cb-header"
          class:partial={selected.size > 0 && !allVisibleSelected}
          class:full={allVisibleSelected}
          onclick={toggleSelectAll}
          title={selected.size === 0
            ? `Select all ${visibleCitekeys.length} visible (⌘A)`
            : (allVisibleSelected
              ? `${selected.size} selected — click to clear`
              : `${selected.size} selected — click to select all ${visibleCitekeys.length} visible`)}
          aria-label="Select all">
          {#if selected.size === 0}
            <span class="cb" aria-hidden="true"></span>
          {:else if allVisibleSelected}
            <span class="cb on" aria-hidden="true">
              <svg width="9" height="7" viewBox="0 0 9 7" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3.5L3.5 6L8 1"/></svg>
            </span>
          {:else}
            <span class="sel-count-mini" aria-hidden="true">{selected.size}</span>
          {/if}
        </button>
        <div class="th idx-col mono">№</div>
        <button class="th title-col" class:sorted={sortBy === "title"} onclick={() => toggleSort("title")}>
          title{sortBy === "title" ? sortDir === "asc" ? " ▴" : " ▾" : ""}
        </button>
        <button class="th author-col" class:sorted={sortBy === "author"} onclick={() => toggleSort("author")}>
          authors{sortBy === "author" ? sortDir === "asc" ? " ▴" : " ▾" : ""}
        </button>
        <button class="th journal-col" class:sorted={sortBy === "journal"} onclick={() => toggleSort("journal")}>
          journal{sortBy === "journal" ? sortDir === "asc" ? " ▴" : " ▾" : ""}
        </button>
        <button class="th year-col" class:sorted={sortBy === "year"} onclick={() => toggleSort("year")}>
          year{sortBy === "year" ? sortDir === "asc" ? " ▴" : " ▾" : ""}
        </button>
        <button class="th added-col" class:sorted={sortBy === "added"} onclick={() => toggleSort("added")}>
          added{sortBy === "added" ? sortDir === "asc" ? " ▴" : " ▾" : ""}
        </button>
        <div class="th in-col">in</div>
      </div>

      {#if listedPapers.length === 0 && orphanCitekeys.length === 0}
        <div class="empty-table">
          <p>
            {activeCollection
              ? "This collection has no papers yet."
              : "No papers match."}
          </p>
          {#if activeCollection}
            <p class="hint">
              Switch source to "all papers" above, then drag rows onto this
              collection in the tree to copy them in.
            </p>
          {/if}
        </div>
      {:else}
        <ul class="tbody" role="rowgroup">
          {#each matchedPapers as p, i (p.citekey)}
            {@const isSel = selected.has(p.citekey)}
            <li role="row">
              <!-- Each row is a draggable <button> — matches the
                   reading-view library list (drag works there). The
                   row's ONE click handler discriminates on event target:
                   click landed inside .cb-col → toggle selection; click
                   anywhere else → preview the paper. Routing both
                   clicks through the button's own handler avoids the
                   nested-interactive-element issue that was blocking
                   drag from starting in WebKit (a child <span role=
                   "button"> with its own click handler swallowed the
                   gesture before dragstart could fire). -->
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <div
                class="row"
                role="button"
                tabindex="0"
                class:selected={isSel}
                draggable="true"
                ondragstart={(e) => setDragData(e, rowsForDrag(p.citekey))}
                ondragend={endDrag}
                onclick={(e) => {
                  const t = e.target as HTMLElement | null;
                  if (t && t.closest(".remove-from-coll")) {
                    void removeFromActive(p.citekey);
                  } else if (t && t.closest(".cb-col")) {
                    toggleSelected(p.citekey);
                  } else {
                    previewPaper(p.citekey);
                  }
                }}
                oncontextmenu={(e) => {
                  e.preventDefault();
                  openCtxMenu(e.clientX, e.clientY, paperRowMenu(p.citekey));
                }}
                title="Click to preview · right-click for actions · drag onto a collection to copy"
              >
                <span
                  class="td cb-col"
                  aria-label={isSel ? "Deselect" : "Select"}
                  title={isSel ? "Deselect this row" : "Select this row"}>
                  <span class="cb" class:on={isSel} aria-hidden="true">
                    {#if isSel}
                      <svg width="9" height="7" viewBox="0 0 9 7" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3.5L3.5 6L8 1"/></svg>
                    {/if}
                  </span>
                </span>
                <span class="td idx-col mono">{String(i + 1).padStart(2, "0")}</span>
                <span class="td title-col">{p.title}</span>
                <span class="td author-col">
                  <span class="author-name">{authorsCellLabel(p)}</span>
                </span>
                <span class="td journal-col">{p.journal ?? "—"}</span>
                <span class="td year-col mono">{p.year}</span>
                <span class="td added-col mono">{shortAdded(p.added)}</span>
                <span class="td in-col">
                  <span class="in-col-pill">
                    {#if (inCount.get(p.citekey) ?? 0) > 0}
                      <span class="in-pill">{inCount.get(p.citekey)}</span>
                    {:else}
                      <span class="in-empty">—</span>
                    {/if}
                  </span>
                  {#if activeCollection}
                    <!-- Hover-revealed remove-from-collection × — sits on
                         top of the count pill. The row's onclick handler
                         routes here via target.closest('.remove-from-coll'),
                         so we don't introduce a nested click target that
                         would break drag. -->
                    <span
                      class="remove-from-coll"
                      role="button"
                      tabindex="-1"
                      aria-label="Remove from this collection"
                      title={`Remove from ${activeCollection.slug}`}>×</span>
                  {/if}
                </span>
              </div>
            </li>
          {/each}

          <!-- Editorial divider — soft search filter announces what's
               below the line and offers to fold it back in. In semantic
               mode the wording shifts so the user knows the embeddings
               picked the order, not a substring match. -->
          {#if hiddenPapers.length > 0}
            <li class="hidden-divider" role="presentation">
              <span class="caps faint">
                {#if semanticActive}
                  + {hiddenPapers.length} less relevant by similarity
                {:else}
                  + {hiddenPapers.length} hidden by filter
                {/if}
              </span>
              <span class="rule"></span>
              <button
                class="show-all"
                onclick={() => (showAllHidden = !showAllHidden)}>
                {showAllHidden ? "hide ↑" : "show all ↓"}
              </button>
            </li>
            {#if showAllHidden}
              {#each hiddenPapers as p, i (p.citekey)}
                {@const isSel = selected.has(p.citekey)}
                <li role="row" class="dimmed">
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <div
                    class="row"
                    role="button"
                    tabindex="0"
                    class:selected={isSel}
                    draggable="true"
                    ondragstart={(e) => setDragData(e, rowsForDrag(p.citekey))}
                    ondragend={endDrag}
                    onclick={(e) => {
                      const t = e.target as HTMLElement | null;
                      if (t && t.closest(".cb-col")) {
                        toggleSelected(p.citekey);
                      } else {
                        previewPaper(p.citekey);
                      }
                    }}
                    oncontextmenu={(e) => {
                      e.preventDefault();
                      openCtxMenu(e.clientX, e.clientY, paperRowMenu(p.citekey));
                    }}
                  >
                    <span class="td cb-col">
                      <span class="cb" class:on={isSel} aria-hidden="true">
                        {#if isSel}
                          <svg width="9" height="7" viewBox="0 0 9 7" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3.5L3.5 6L8 1"/></svg>
                        {/if}
                      </span>
                    </span>
                    <span class="td idx-col mono">{String(matchedPapers.length + i + 1).padStart(2, "0")}</span>
                    <span class="td title-col">{p.title}</span>
                    <span class="td author-col">
                      <span class="author-name">{authorsCellLabel(p)}</span>
                    </span>
                    <span class="td journal-col">{p.journal ?? "—"}</span>
                    <span class="td year-col mono">{p.year}</span>
                    <span class="td added-col mono">{shortAdded(p.added)}</span>
                    <span class="td in-col">
                      {#if (inCount.get(p.citekey) ?? 0) > 0}
                        <span class="in-pill">{inCount.get(p.citekey)}</span>
                      {:else}
                        <span class="in-empty">—</span>
                      {/if}
                    </span>
                  </div>
                </li>
              {/each}
            {/if}
          {/if}

          {#each orphanCitekeys as ck (ck)}
            <li role="row" class="orphan">
              <!-- Orphan row — same .row grid layout but a passive
                   <div>; no drag, no select, just the broken-reference
                   info and an × to remove the citekey from the active
                   collection. -->
              <div class="row static">
                <span class="td cb-col"></span>
                <span class="td idx-col mono">··</span>
                <span class="td title-col">{ck}</span>
                <span class="td author-col">—</span>
                <span class="td journal-col">missing</span>
                <span class="td year-col mono">—</span>
                <span class="td added-col mono">—</span>
                <span class="td in-col">
                  {#if activeCollection}
                    <button
                      class="orphan-x"
                      onclick={() => activeCollection && removePaperFromCollection(activeCollection.slug, ck).catch((e) => toast(`Remove failed: ${e}`, "error"))}
                      title={`Remove orphan ${ck} from ${activeCollection.slug}`}>×</button>
                  {/if}
                </span>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
      {/if}

      <!-- Preview overlay — floats over the table only; the folders
           pane on the left stays visible and clickable. The library
           table behind is glass-blurred so the user can tell it's still
           there. Close via × button, "← back to organizing", or Esc. -->
      {#if previewCitekey}
        {@const ck = previewCitekey}
        {@const previewPaperMeta = libraryState.papers.find((p) => p.citekey === ck)}
        {@const isSel = selected.has(ck)}
        <div class="preview-overlay" role="dialog" aria-modal="true" aria-label="Paper preview">
          <div class="preview-scrim"></div>
          <div class="preview-paper">
            <!-- Single header bar across the top of the floating paper:
                 selection checkbox on the left (toggles the previewed
                 paper's membership in the multi-select set) and the
                 back-link + close × on the right. To file the previewed
                 paper into a collection, close the preview (Esc / ×)
                 and drag its row from the table instead — having a
                 second drag source inside the floating overlay was
                 visually confusing. -->
            <div class="preview-header">
              {#if previewPaperMeta}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <span
                  class="preview-cb"
                  role="button"
                  tabindex="-1"
                  aria-pressed={isSel}
                  aria-label={isSel ? "Deselect" : "Select"}
                  onclick={() => toggleSelected(ck)}
                  title={isSel ? "Deselect this paper" : "Select this paper"}>
                  <span class="cb" class:on={isSel} aria-hidden="true">
                    {#if isSel}
                      <svg width="9" height="7" viewBox="0 0 9 7" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3.5L3.5 6L8 1"/></svg>
                    {/if}
                  </span>
                </span>
              {/if}
              {#if activeCollection && previewPaperMeta}
                <!-- "Remove from collection" — only when the user is
                     viewing a specific collection (not "all papers"
                     or "inbox"). Mirrors the hover-revealed × in the
                     IN column of the table; same removePaperFromCollection
                     call. Auto-closes the preview on success so the
                     table catches up. -->
                <button
                  class="remove-coll-btn"
                  onclick={async () => {
                    if (!activeCollection) return;
                    await removeFromActive(ck);
                    closePreview();
                  }}
                  title={`Remove this paper from ${activeCollection.slug} (stays in the library)`}>
                  <span class="x">×</span>
                  <span class="label">Remove from <em>{activeCollection.slug}</em></span>
                </button>
              {/if}
              <div class="header-spacer"></div>
              <button class="back-link" onclick={closePreview}>← back to organizing</button>
              <button class="close-x" onclick={closePreview} title="Close preview (Esc)" aria-label="Close preview">×</button>
            </div>
            <div class="preview-body">
              <div class="preview-pdf">
                <PDFView citekey={ck} />
              </div>
              <div class="preview-notes">
                <NoteEditor citekey={ck} />
              </div>
            </div>
          </div>
        </div>
      {/if}

      <!-- Inbox PDF preview — same overlay shape as the paper preview
           but with no NoteEditor (the PDF isn't filed yet, so there's
           no PaperNotes/{citekey}.md to edit). Header carries a
           "retry filing" button so the user can try the auto-file
           pipeline again right from the preview. -->
      {#if previewInboxPath}
        {@const inboxPath = previewInboxPath}
        <div class="preview-overlay" role="dialog" aria-modal="true" aria-label="Inbox PDF preview">
          <div class="preview-scrim"></div>
          <div class="preview-paper">
            <div class="preview-header">
              <span class="preview-filename" title={inboxPath}>
                <span class="eyebrow">Inbox</span>
                <span class="sep">·</span>
                <span class="name">{previewInboxFilename}</span>
              </span>
              <button
                class="preview-file-btn"
                onclick={async () => {
                  const result = await retryFile(inboxPath);
                  if (result.status === "filed") {
                    toast(`Filed → ${result.citekey}`);
                    closePreview();
                  } else if (result.status === "duplicate") {
                    toast(`Already in vault as ${result.citekey ?? "(unknown)"}`, "error");
                  } else {
                    toast(`Filing failed: ${result.detail ?? result.status}`, "error");
                  }
                }}
                title="Run the auto-file pipeline on this PDF">file it</button>
              <div class="header-spacer"></div>
              <button class="back-link" onclick={closePreview}>← back to inbox</button>
              <button class="close-x" onclick={closePreview} title="Close preview (Esc)" aria-label="Close preview">×</button>
            </div>
            <div class="preview-body">
              <div class="preview-pdf inbox-pdf-full">
                <PDFView pdfUrl={convertFileSrc(inboxPath)} />
              </div>
            </div>
          </div>
        </div>
      {/if}
    </section>
  </div>
</section>

{#if findModalFor}
  <InboxFindModal
    pdfPath={findModalFor.path}
    filename={findModalFor.filename}
    onClose={closeFindModal}
  />
{/if}

<style>
  /* ----- shell ---------------------------------------------------------- */
  section.organize {
    height: 100%;
    background: var(--backdrop);
    color: var(--ink);
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    /* Block text selection across the whole organize view — nothing
       here is meant to be selected (the masthead, toolbar, column
       headers, and rows are all click/drag targets). Inputs and
       textareas opt back in below so the search field still works. */
    user-select: none;
    -webkit-user-select: none;
  }
  section.organize input {
    user-select: text;
    -webkit-user-select: text;
  }

  .top-strip {
    flex: 0 0 auto;
    height: 38px;
    padding: 0 22px 0 var(--tl-pad);
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--panel);
    /* macOS overlay-title window has no native title bar; the strip
       below the traffic lights IS the drag handle. Mirror the Tauri
       `data-tauri-drag-region` attribute as `-webkit-app-region: drag`
       since some Tauri runtime builds rely on the CSS form. Children
       opt out below so the ViewSwitch buttons receive clicks. */
    -webkit-app-region: drag;
  }
  .top-strip > * {
    -webkit-app-region: no-drag;
  }
  .strip-spacer {
    flex: 1;
  }
  .top-meta {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-50);
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }

  .columns {
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    grid-template-columns: 340px 1fr;
  }

  /* ----- folders pane (left) ------------------------------------------- */
  aside.folders-pane {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border-right: 1px solid var(--ink-12);
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    /* Tree labels are click/drag-drop targets, never something the user
       wants to highlight. Suppress text selection so a quick mousedown
       on a row label doesn't start a text-selection gesture. */
    user-select: none;
    -webkit-user-select: none;
  }
  .pane-head {
    flex: 0 0 auto;
    padding: 14px 22px 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .pane-head .caps {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  .pane-head .hint {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--ink-30);
  }

  .tree-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: 8px;
    /* Force top-aligned packing — without an explicit flex layout the
       inner rows were drifting toward the middle of the column on the
       built app (most likely the .columns grid was stretching the aside
       to fill its row, and the rows inside were inheriting some implicit
       distribution). align-content: start keeps them stuck under the
       header regardless of the column's height. */
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    align-content: flex-start;
  }
  .tree-scroll > * {
    flex-shrink: 0;
  }
  .tree-bottom-pad {
    height: 12px;
  }

  /* tree row — same vocabulary for both root and nested levels */
  .tree-row,
  .tree-row-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 14px 5px calc(10px + var(--depth, 0) * 14px);
    border-left: 2px solid transparent;
    cursor: pointer;
    height: 28px;
    background: transparent;
    border-top: 0;
    border-right: 0;
    border-bottom: 0;
    width: 100%;
    text-align: left;
    border-radius: 0;
    color: inherit;
    font: inherit;
  }
  .tree-row:hover {
    color: var(--accent);
  }
  .tree-row.active,
  .tree-row-wrap.active {
    background: var(--panel-alt);
    border-left-color: var(--accent);
  }
  .tree-row-wrap.drop-target {
    background: var(--drop-soft);
    border-left: 2px dashed var(--accent);
  }
  .caret {
    /* Bumped from the design pack's 8.5px — at the live render scale
       the chevron was barely legible against the cream backdrop. 13px
       is large enough to read and click without cramming the row. */
    width: 18px;
    height: 18px;
    line-height: 18px;
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-size: 13px;
    text-align: center;
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
    transform: rotate(-90deg);
    transition: transform 80ms;
  }
  .caret:hover:not(.invisible) {
    color: var(--ink);
  }
  .tree-row-wrap.active .caret {
    transform: none;
  }
  .caret.invisible {
    visibility: hidden;
  }
  .caret-spacer {
    width: 18px;
    flex-shrink: 0;
  }
  .leaf-icon {
    width: 12px;
    text-align: center;
    flex-shrink: 0;
    color: var(--ink-50);
    font-size: 10px;
  }
  .leaf-icon.mono {
    font-family: var(--mono);
  }
  .leaf-icon.serif {
    font-family: var(--serif);
    font-style: italic;
  }
  /* Two near-identical buttons that need slightly different external
     sizing: .leaf-btn lives INSIDE .tree-row-wrap (a flex row), so it
     should grow horizontally and span the row height. .all-row is a
     direct child of .tree-scroll (a flex column), so it must NOT grow
     — it sits at its row height (28px). Earlier they shared a single
     rule with `flex: 1` + `height: 100%`, which made .all-row stretch
     to fill the entire column vertically. */
  .leaf-btn,
  .all-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px;
    border: 0;
    background: transparent;
    color: var(--ink);
    font-family: var(--serif);
    font-size: 12.5px;
    font-weight: 500;
    letter-spacing: -0.2px;
    cursor: pointer;
    overflow: hidden;
    border-radius: 0;
  }
  .leaf-btn {
    flex: 1;
    height: 100%;
  }
  .leaf-btn:hover:not(:disabled) {
    color: var(--accent);
  }
  .leaf-btn:disabled {
    cursor: default;
    color: var(--ink-50);
  }
  .leaf-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .leaf-name.group-name {
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--ink-70);
  }
  .tree-row.active .leaf-name,
  .tree-row-wrap.active .leaf-name {
    color: var(--ink);
    font-weight: 600;
  }
  .leaf-count {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-30);
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }
  .tree-row.active .leaf-count,
  .tree-row-wrap.active .leaf-count {
    color: var(--accent);
  }

  .row-actions {
    display: flex;
    gap: 0;
    align-items: center;
    opacity: 0;
    transition: opacity 80ms ease;
    flex-shrink: 0;
  }
  .tree-row-wrap:hover .row-actions {
    opacity: 1;
  }
  .row-btn {
    border: 0;
    background: transparent;
    color: var(--ink-30);
    font-size: 13px;
    line-height: 1;
    padding: 0 6px;
    cursor: pointer;
  }
  .row-btn:hover {
    color: var(--accent);
  }

  .create-row {
    display: flex;
    align-items: center;
    padding: 4px 8px 4px calc(28px + var(--depth) * 14px);
  }
  .create-input,
  .rename-input {
    flex: 1;
    border: 1px solid var(--ink-30);
    background: var(--surface);
    color: var(--ink);
    font-family: var(--mono);
    font-size: 11px;
    padding: 3px 6px;
    border-radius: 1px;
    outline: none;
  }
  .create-input:focus,
  .rename-input:focus {
    border-color: var(--accent);
  }

  /* "+ new collection" — dashed editorial affordance, fixed at the bottom */
  .new-coll {
    flex: 0 0 auto;
    margin: 8px 18px;
    padding: 6px 10px;
    border: 1px dashed var(--ink-30);
    background: transparent;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--ink-50);
    font-family: var(--serif);
    font-style: italic;
    font-size: 11.5px;
    cursor: pointer;
    border-radius: 0;
  }
  .new-coll:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .new-coll .plus {
    color: var(--accent);
    font-family: var(--mono);
    font-style: normal;
    font-size: 13px;
  }

  /* ----- table pane (right) -------------------------------------------- */
  section.table-pane {
    display: flex;
    flex-direction: column;
    background: var(--backdrop);
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    position: relative;
  }
  .masthead {
    flex: 0 0 auto;
    padding: 18px 28px 14px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--panel);
    position: relative;
  }
  .masthead .eyebrow {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  .title-row {
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin-top: 4px;
  }
  .source-trigger {
    border: 0;
    background: transparent;
    padding: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    color: var(--ink);
  }
  .source-name {
    font-family: var(--serif);
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.6px;
    line-height: 1.05;
  }
  .source-trigger .chev {
    color: var(--ink-50);
    font-size: 16px;
    font-weight: 400;
  }
  .paper-count {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--ink-50);
    font-variant-numeric: tabular-nums;
  }
  .masthead-helper {
    margin-top: 4px;
    font-family: var(--serif);
    font-style: italic;
    font-size: 12.5px;
    color: var(--ink-50);
  }
  .active-description {
    margin-top: 8px;
    padding: 6px 10px;
    border-left: 2px solid var(--accent);
    font-family: var(--serif);
    font-style: italic;
    font-size: 12px;
    line-height: 1.4;
    color: var(--ink-70);
    background: var(--panel-alt);
  }

  .source-menu {
    position: absolute;
    z-index: 5;
    top: 64px;
    left: 28px;
    margin: 0;
    padding: 4px 0;
    list-style: none;
    background: var(--panel);
    border: 1px solid var(--ink);
    box-shadow: 0 8px 24px rgba(26, 22, 18, 0.18);
    min-width: 320px;
    max-height: 360px;
    overflow-y: auto;
  }
  .source-menu li {
    margin: 0;
  }
  .source-menu button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 6px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--ink);
    font-family: var(--serif);
    font-size: 12.5px;
    cursor: pointer;
    border-radius: 0;
  }
  .source-menu button:hover {
    background: var(--panel-alt);
  }
  .source-menu button.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
  .source-menu .m-icon {
    width: 14px;
    color: var(--ink-50);
    font-family: var(--mono);
    font-size: 11px;
    text-align: center;
  }
  .source-menu .m-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .source-menu .m-count {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-30);
    font-variant-numeric: tabular-nums;
  }

  /* search + sort row */
  .toolbar {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 28px;
    background: var(--panel);
    border-bottom: 1px solid var(--ink-12);
  }
  .search-row {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 28px;
    flex: 0 0 380px;
    border-bottom: 1.5px solid var(--ink);
    padding-left: 2px;
  }
  .search-icon {
    color: var(--ink-70);
    display: inline-flex;
  }
  .search-row input {
    flex: 1;
    border: 0;
    background: transparent;
    outline: none;
    font-family: var(--serif);
    font-size: 13px;
    color: var(--ink);
    font-weight: 500;
  }
  .search-row input::placeholder {
    color: var(--ink-50);
    font-style: italic;
  }
  .clear-q {
    border: 0;
    background: transparent;
    color: var(--ink-30);
    font-family: var(--mono);
    font-size: 13px;
    cursor: pointer;
  }
  .clear-q:hover {
    color: var(--ink);
  }

  /* SEM toggle — same shape as the reading view's, sits inside the
     search row. Outline by default, filled accent when on. Disabled
     state has reduced opacity + cursor: not-allowed. */
  .sem-toggle {
    flex: 0 0 auto;
    border: 1px solid var(--accent);
    background: transparent;
    color: var(--accent);
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.2px;
    padding: 2px 6px;
    cursor: pointer;
    border-radius: 0;
    line-height: 1;
  }
  .sem-toggle.on {
    background: var(--accent);
    color: var(--panel);
  }
  .sem-toggle:hover:not(:disabled):not(.on) {
    background: var(--accent-soft);
  }
  .sem-toggle:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    border-color: var(--ink-30);
    color: var(--ink-50);
  }
  .toolbar-spacer {
    flex: 1;
  }
  .sort-caption {
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
  }
  .sort-caption .dir {
    color: var(--ink);
  }

  /* Small "N" in the cb-col header when there's an active selection.
     Click clears all selected rows. The drag-onto-collection gesture
     is obvious enough that it doesn't need a dedicated bar. */
  .sel-count-mini {
    border: 0;
    background: var(--accent);
    color: var(--panel);
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 0.2px;
    line-height: 1;
    padding: 2px 5px;
    cursor: pointer;
    border-radius: 1px;
    min-width: 16px;
    text-align: center;
  }
  .sel-count-mini:hover {
    background: var(--ink);
  }

  /* ----- table grid ----------------------------------------------------- */
  /* Column tracks: cb · idx · title (flex) · authors · journal · year · added · in.
     Applied to both the header (.thead) and each row's inner .row element
     so the columns line up exactly. */
  .thead,
  .tbody .row {
    display: grid;
    grid-template-columns: 32px 32px minmax(180px, 2fr) 140px minmax(120px, 1.2fr) 56px 100px 50px;
    align-items: center;
    column-gap: 16px;
    padding: 0 28px 0 18px;
  }
  .thead {
    flex: 0 0 auto;
    height: 32px;
    border-top: 1px solid var(--ink);
    border-bottom: 1px solid var(--ink-07);
    background: var(--panel);
  }
  .th {
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
    background: transparent;
    border: 0;
    padding: 0;
    text-align: left;
    cursor: pointer;
    border-radius: 0;
  }
  .th.sorted {
    color: var(--ink);
  }
  .th:hover {
    color: var(--ink);
  }
  .th.idx-col {
    cursor: default;
    color: var(--ink-50);
  }
  .th.cb-col,
  .th.idx-col {
    cursor: default;
  }
  .th.cb-col {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .th.year-col,
  .th.added-col,
  .th.in-col {
    text-align: right;
  }

  .tbody {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    flex: 1 1 auto;
    background: var(--panel);
  }
  /* Each tbody row is <li><button class="row" draggable="true">…</button>.
     The <li> is just a list-semantic wrapper — the inner <button> is
     the drag source AND the click target, mirroring the reading-view
     library list (where drag is known to work). Trying to drag from a
     plain <li draggable> didn't fire dragstart in WebKit. */
  .tbody li {
    border-bottom: 1px solid var(--ink-07);
    user-select: none;
    -webkit-user-select: none;
  }
  .tbody .row {
    height: 38px;
    width: 100%;
    background: transparent;
    border: 0;
    border-radius: 0;
    border-left: 2px solid transparent;
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    user-select: none;
    -webkit-user-select: none;
    /* Force WebKit to treat mousedown-and-move as a drag start, not a
       text-selection gesture. Without this the row would refuse to
       drag. */
    -webkit-user-drag: element;
  }
  .tbody .row.static {
    cursor: default;
    -webkit-user-drag: none;
  }
  .tbody .row .td {
    user-select: none;
    -webkit-user-select: none;
  }
  .tbody .row:hover:not(.static) {
    background: var(--hover);
  }
  .tbody .row.selected {
    background: var(--accent-soft);
    border-left-color: var(--accent);
  }
  .tbody .row.selected:hover {
    background: var(--accent-mid);
  }
  .td {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* The cb-col cell is the selection click target. The row's ONE click
     handler routes the click by event-target — anything inside .cb-col
     toggles selection, anything else opens the preview. The entire cell
     is the hit area so the user can still aim "at the checkbox" without
     pixel accuracy. */
  .td.cb-col {
    overflow: visible;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    cursor: pointer;
  }
  .tbody .row .td.cb-col:hover {
    background: var(--ink-07);
  }
  .tbody .row.selected .td.cb-col:hover {
    background: var(--accent-mid);
  }
  .cb {
    width: 13px;
    height: 13px;
    background: var(--panel);
    border: 1px solid var(--ink-30);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .cb.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .td.idx-col {
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 600;
    color: var(--ink-30);
    letter-spacing: 0.2px;
    font-variant-numeric: tabular-nums;
  }
  .tbody .row.selected .td.idx-col {
    color: var(--accent);
  }
  .td.title-col {
    font-family: var(--serif);
    font-size: 13.5px;
    font-weight: 500;
    letter-spacing: -0.2px;
    color: var(--ink);
    line-height: 1.3;
  }
  .tbody .row.selected .td.title-col {
    font-weight: 600;
  }
  .td.author-col {
    font-family: var(--sans);
    font-size: 11.5px;
    color: var(--ink-70);
  }
  .td.author-col .author-name {
    color: var(--ink);
    font-weight: 500;
  }
  .td.journal-col {
    font-family: var(--serif);
    font-style: italic;
    font-size: 12px;
    color: var(--ink-70);
  }
  .td.year-col,
  .td.added-col {
    font-family: var(--mono);
    font-size: 10.5px;
    color: var(--ink-50);
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .td.in-col {
    text-align: right;
  }
  .in-pill {
    display: inline-block;
    font-family: var(--mono);
    font-size: 9.5px;
    color: var(--ink-70);
    border: 0.5px solid var(--ink-30);
    padding: 1px 6px;
  }
  .in-empty {
    font-family: var(--mono);
    font-size: 9.5px;
    color: var(--ink-30);
  }

  /* In-col stacking: pill is shown by default; on row hover (when we're
     viewing a collection) the × replaces it. Same cell width, no
     layout shift. The × routes through the row's onclick via
     target.closest('.remove-from-coll'), so it doesn't introduce a
     nested click target. */
  .td.in-col {
    position: relative;
    text-align: right;
  }
  .in-col-pill {
    transition: opacity 80ms ease;
  }
  .remove-from-coll {
    position: absolute;
    inset: 0;
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    padding: 0 6px;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition: opacity 80ms ease;
  }
  .tbody .row:hover .remove-from-coll {
    opacity: 1;
    color: var(--accent);
  }
  .tbody .row:hover .in-col-pill {
    opacity: 0;
  }

  /* Inbox pseudo-row in the tree — same shape as "all papers" but with
     a faint accent dot when there are unfiled PDFs waiting, so the
     user notices something needs attention. */
  .inbox-row .leaf-icon {
    color: var(--ink-30);
  }
  .inbox-row.has-items .leaf-icon,
  .inbox-row.has-items .leaf-count {
    color: var(--accent);
  }

  /* Inbox table rows use the same grid as the paper rows but with a
     different track set (no checkbox/authors/year etc., just filename
     + dates + size + actions). The .inbox-thead and .inbox-row-grid
     classes override the shared grid-template-columns. */
  .thead.inbox-thead,
  .tbody li.inbox-li .row.inbox-row-grid {
    grid-template-columns: 32px minmax(180px, 3fr) 100px 70px 100px;
  }
  .inbox-actions {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
  }
  .inbox-action {
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    padding: 4px 6px;
    cursor: pointer;
  }
  .inbox-action:hover {
    color: var(--accent);
  }
  .inbox-action.danger {
    font-family: var(--mono);
    font-size: 14px;
    letter-spacing: 0;
    text-transform: none;
  }
  .inbox-action.danger:hover {
    color: var(--accent-bright, var(--accent));
  }

  .tbody li.orphan {
    color: var(--ink-50);
    font-style: italic;
    cursor: default;
  }
  .tbody li.orphan .td.title-col {
    font-family: var(--mono);
    font-size: 10.5px;
    color: var(--ink-50);
  }
  .orphan-x {
    border: 0;
    background: transparent;
    color: var(--ink-30);
    font-size: 13px;
    cursor: pointer;
    padding: 0 4px;
  }
  .orphan-x:hover {
    color: var(--accent);
  }

  .empty-table {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px;
    color: var(--ink-50);
    text-align: center;
    background: var(--panel);
  }
  .empty-table p {
    margin: 0 0 8px;
    font-size: 12px;
  }
  .empty-table .hint {
    font-size: 11px;
    color: var(--ink-50);
    max-width: 360px;
  }

  /* "+N" badge inline on a hovered tree row during multi-drag. Replaces
     the row's static count for the duration of the drag so the gesture
     reads as "drop here to add N papers." */
  .drop-count {
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: 0.4px;
    flex-shrink: 0;
  }

  /* Tag-chip strip — single-row scroll by default, multi-row when
     expanded. Active chips are filled black per Direction B. */
  .tag-strip {
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: 540px;
    min-width: 0;
  }
  .tag-toggle {
    flex: 0 0 auto;
    border: 0;
    background: transparent;
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
    cursor: pointer;
    padding: 0 6px 0 0;
  }
  .tag-toggle:hover {
    color: var(--ink);
  }
  .tag-strip .chips {
    display: flex;
    flex-wrap: nowrap;
    gap: 4px;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  .tag-strip.expanded .chips {
    flex-wrap: wrap;
    overflow-x: visible;
  }
  .chip {
    flex-shrink: 0;
    padding: 2px 8px;
    background: transparent;
    color: var(--ink-70);
    border: 0.5px solid var(--ink-30);
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 0;
    white-space: nowrap;
  }
  .chip:hover {
    border-color: var(--ink);
    color: var(--ink);
  }
  .chip.on {
    background: var(--ink);
    color: var(--backdrop);
    border-color: var(--ink);
  }
  .chip.cite {
    font-style: italic;
  }
  .chip-clear {
    flex-shrink: 0;
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 10px;
    cursor: pointer;
    padding: 0 4px;
  }
  .chip-clear:hover {
    color: var(--accent);
  }

  /* "+N hidden by filter / show all ↓" editorial divider between the
     matched results and the rest. The hidden rows themselves render
     dimmed, so the user can still find them but they read as secondary. */
  .hidden-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 32px;
    padding: 0 28px;
    background: var(--panel);
    border-bottom: 1px solid var(--ink-07);
  }
  .hidden-divider .caps.faint {
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
  }
  .hidden-divider .rule {
    flex: 1;
    height: 1px;
    background: var(--ink-07);
  }
  .show-all {
    border: 0;
    background: transparent;
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--accent);
    cursor: pointer;
  }
  .show-all:hover {
    color: var(--ink);
  }
  .tbody li.dimmed {
    opacity: 0.55;
  }
  .tbody li.dimmed:hover {
    opacity: 1;
  }

  /* Preview overlay — floats inside the table-pane only, so the folders
     tree on the left remains visible and clickable. The scrim uses
     backdrop-filter for a glass blur over the still-mounted table. */
  .preview-overlay {
    position: absolute;
    inset: 0;
    z-index: 30;
    overflow: hidden;
  }
  /* Scrim — dim cream wash behind the floating preview-paper. The
     earlier version used backdrop-filter:blur, but in the Tauri
     WKWebView that broke drag: the cursor crossing a blurred region
     during a drag would (a) blur the folders-pane content the user
     was throwing toward and (b) catch dragover events instead of
     letting them reach the tree. `pointer-events: none` lets HTML5
     drag events pass through to the elements underneath, so a drag
     from the preview's chip can travel all the way to a tree node
     on the left without losing the gesture. Click-to-dismiss isn't
     possible anymore, but Esc and the × button cover that. */
  .preview-scrim {
    position: absolute;
    inset: 0;
    background: rgba(26, 22, 18, 0.18);
    pointer-events: none;
  }
  .preview-paper {
    position: absolute;
    inset: 20px 20px 20px 20px;
    background: var(--panel);
    border: 0.5px solid var(--ink-12);
    box-shadow:
      0 1px 1px rgba(0, 0, 0, 0.04),
      0 24px 60px rgba(26, 22, 18, 0.32),
      0 6px 16px rgba(26, 22, 18, 0.18);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  /* Single header bar across the top of the preview-paper. Holds the
     preview's chrome (selection checkbox, drag-onto-collection chip,
     "← back to organizing" link, close ×) above both the PDF toolbar
     and the notes header, so neither gets occluded. */
  .preview-header {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--panel);
    z-index: 5;
  }
  .header-spacer {
    flex: 1;
  }
  /* Editorial checkbox button — slim square that sits in the preview's
     header bar next to the drag chip. Same vocabulary as the table cb;
     click toggles the previewed paper's membership in the same
     multi-select set the table cb-col cells write to. */
  .preview-cb {
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--ink-30);
    background: var(--panel);
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
  }
  .preview-cb:hover {
    border-color: var(--accent);
  }
  .preview-cb .cb {
    width: 13px;
    height: 13px;
  }

  /* "Remove from {collection}" — editorial pill, only rendered when
     the user is viewing a specific collection. Visually distinct from
     the close × so the destructive scope is clear (this paper from
     this collection, not delete-the-paper). */
  .remove-coll-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border: 1px solid var(--ink-30);
    background: transparent;
    color: var(--ink-70);
    font-family: var(--sans);
    font-size: 10.5px;
    font-weight: 500;
    letter-spacing: 0.2px;
    cursor: pointer;
    border-radius: 0;
  }
  .remove-coll-btn:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .remove-coll-btn .x {
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1;
    color: var(--accent);
  }
  .remove-coll-btn .label em {
    font-family: var(--serif);
    font-style: italic;
    font-weight: 500;
  }

  /* CrossRef search form — expanded under an Inbox row when the user
     clicks "find" or after a retry returns no-identifier. Three
     optional input fields (title / author / year), a Search button,
     and a list of candidates returned by the script. Clicking a
     candidate files the PDF with that DOI. */
  .inbox-search {
    border-top: 1px dashed var(--ink-12);
    background: var(--panel-alt);
    padding: 10px 28px 14px 18px;
  }
  .inbox-search-form {
    display: flex;
    align-items: flex-end;
    gap: 10px;
    flex-wrap: wrap;
  }
  .inbox-search-field {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1 1 180px;
    min-width: 0;
  }
  .inbox-search-field.year-field {
    flex: 0 0 70px;
  }
  .caps-label {
    font-family: var(--sans);
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
  }
  .inbox-search-field input {
    border: 0;
    border-bottom: 1px solid var(--ink-30);
    background: transparent;
    font-family: var(--serif);
    font-size: 12.5px;
    color: var(--ink);
    padding: 3px 0;
    outline: none;
  }
  .inbox-search-field input:focus {
    border-bottom-color: var(--accent);
  }
  .inbox-search-go {
    border: 1px solid var(--accent);
    background: transparent;
    color: var(--accent);
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    padding: 5px 12px;
    cursor: pointer;
    border-radius: 0;
    flex-shrink: 0;
  }
  .inbox-search-go:hover:not(:disabled) {
    background: var(--accent);
    color: var(--panel);
  }
  .inbox-search-go:disabled {
    opacity: 0.5;
    cursor: wait;
  }
  .inbox-search-error {
    margin-top: 10px;
    font-family: var(--serif);
    font-style: italic;
    font-size: 11px;
    color: var(--ink-70);
  }
  .inbox-search-results {
    list-style: none;
    margin: 12px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .inbox-candidate {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    text-align: left;
    border: 0;
    background: var(--panel);
    border-left: 2px solid transparent;
    padding: 8px 12px;
    cursor: pointer;
    border-radius: 0;
  }
  .inbox-candidate:hover:not(:disabled) {
    border-left-color: var(--accent);
    background: var(--surface);
  }
  .inbox-candidate:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .inbox-candidate-title {
    font-family: var(--serif);
    font-size: 12.5px;
    font-weight: 500;
    color: var(--ink);
    line-height: 1.3;
  }
  .inbox-candidate-meta {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-family: var(--sans);
    font-size: 10.5px;
    color: var(--ink-70);
  }
  .inbox-candidate-meta .dim {
    color: var(--ink-30);
  }
  .inbox-candidate-meta .mono {
    font-family: var(--mono);
    font-size: 10px;
  }
  .inbox-candidate-meta .doi {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 320px;
  }
  .inbox-candidate-meta .grow {
    flex: 1;
  }
  .inbox-candidate-meta .score {
    color: var(--ink-30);
  }

  .inbox-action.active {
    color: var(--accent);
  }

  /* Inbox preview chrome — slightly different from the paper preview.
     Filename block on the left (eyebrow caps "Inbox" + filename),
     "file it" action, then back-link + close × on the right. */
  .preview-filename {
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    overflow: hidden;
    flex-shrink: 1;
    min-width: 0;
  }
  .preview-filename .eyebrow {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--accent);
    flex-shrink: 0;
  }
  .preview-filename .sep {
    color: var(--ink-30);
    flex-shrink: 0;
  }
  .preview-filename .name {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .preview-file-btn {
    border: 1px solid var(--accent);
    background: var(--accent);
    color: var(--panel);
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    padding: 4px 12px;
    cursor: pointer;
    border-radius: 0;
  }
  .preview-file-btn:hover {
    background: var(--ink);
    border-color: var(--ink);
  }
  .inbox-pdf-full {
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
  /* Inbox filename → preview click target. Reset button defaults; the
     hover treatment is the row's, not the button's. */
  .inbox-filename-btn {
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    color: inherit;
    font: inherit;
  }
  .inbox-filename-btn:hover {
    color: var(--accent);
  }

  .back-link {
    border: 0;
    background: transparent;
    font-family: var(--sans);
    font-size: 10.5px;
    font-weight: 500;
    color: var(--ink-70);
    letter-spacing: 0.2px;
    cursor: pointer;
    padding: 6px 8px;
  }
  .back-link:hover {
    color: var(--ink);
    background: var(--panel-alt);
  }
  .close-x {
    width: 36px;
    height: 36px;
    padding: 0;
    background: var(--panel);
    color: var(--ink);
    border: 1px solid var(--ink);
    border-radius: 0;
    font-family: var(--sans);
    font-size: 22px;
    font-weight: 300;
    line-height: 1;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 6px rgba(26, 22, 18, 0.18);
  }
  .close-x:hover {
    background: var(--ink);
    color: var(--panel);
  }
  .preview-body {
    flex: 1;
    display: flex;
    min-height: 0;
    min-width: 0;
  }
  .preview-pdf {
    flex: 1;
    min-width: 0;
    min-height: 0;
    border-right: 1px solid var(--ink-12);
    display: flex;
    flex-direction: column;
  }
  .preview-notes {
    width: 360px;
    min-height: 0;
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }
</style>

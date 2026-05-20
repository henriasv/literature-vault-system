<script lang="ts">
  import {
    libraryState,
    applyFilter,
    setSearchMode,
    scheduleSemanticSearch,
    semanticPapers,
    toggleTagFilter,
    clearTagFilter,
    setCollectionFilter,
    allTags,
    type SortKey,
  } from "../state/library.svelte";
  import {
    collectionsState,
    addPaperToCollection,
    membersOf,
  } from "../state/collections.svelte";
  import {
    dndState,
    startInternalDrag,
    finishInternalDrag,
  } from "../state/dnd.svelte";
  import {
    inboxState,
    refreshInbox,
    requestOpenInbox,
  } from "../state/inbox.svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";

  /** Initiate a native window-drag from a JS mousedown handler. Tauri's
   *  `data-tauri-drag-region` attribute isn't firing in this build —
   *  most likely because the OS drag-drop handler (dragDropEnabled:
   *  true) competes for mousedown events. Trigger startDragging
   *  ourselves: drag whenever the click landed on the strip or one of
   *  its non-interactive children, opt out only when it landed on a
   *  button / link / input / role=button (the ViewSwitch buttons,
   *  primarily). */
  function onStripMouseDown(e: MouseEvent): void {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest('button, a, input, textarea, [role="button"], [role="tab"]')) {
      return;
    }
    e.preventDefault();
    getCurrentWindow()
      .startDragging()
      .catch((err) => console.error("startDragging (library strip) failed:", err));
  }
  import ViewSwitch from "./ViewSwitch.svelte";
  import { tabsState, openInTab, openInNewTab } from "../state/tabs.svelte";
  import { prefsState } from "../state/prefs.svelte";
  import { writeText as clipboardWriteText } from "@tauri-apps/plugin-clipboard-manager";
  import { onMount } from "svelte";
  import { readBibtex, vaultRootDisplay } from "../lib/vault";
  import { openCtxMenu } from "../state/ctxmenu.svelte";
  import { paperRowMenu } from "../lib/paper-menu";
  import { toast } from "../state/toast.svelte";

  let searchInput: HTMLInputElement | undefined = $state();
  /** Whether the tag chip strip is expanded (multi-row) or collapsed
   *  (single-row, horizontal scroll). Toggled by the "Tags ▾" button. */
  let tagsExpanded = $state(false);

  /** Pretty form of the active vault path (`$HOME` → `~`) — shown under the
   *  masthead so the user always knows which vault is loaded. Hydrated on
   *  mount; empty string until then. */
  let vaultPath = $state("");
  onMount(() => {
    void (async () => {
      try {
        vaultPath = await vaultRootDisplay();
      } catch {
        /* if it fails the masthead just hides the line */
      }
    })();
  });

  /** Collections fold-out state — collapsed by default, expands a
   *  read-only tree below the header so users can browse without
   *  entering organize mode. */
  let collectionsFoldoutOpen = $state(false);
  let foldoutExpanded = $state<Set<string>>(new Set());
  function toggleFoldoutExpand(slug: string) {
    const next = new Set(foldoutExpanded);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    foldoutExpanded = next;
  }

  interface FoldoutTreeNode {
    slug: string;
    leafName: string;
    isCollection: boolean;
    count: number;
    children: FoldoutTreeNode[];
  }
  /** Build the same nested tree the organize view uses, but stripped to
   *  the fields the read-only fold-out needs. */
  const foldoutTree = $derived.by<FoldoutTreeNode[]>(() => {
    const bySlug = new Map(collectionsState.list.map((c) => [c.slug, c]));
    const allSlugs = new Set<string>();
    for (const c of collectionsState.list) {
      allSlugs.add(c.slug);
      const parts = c.slug.split("/");
      for (let i = 1; i < parts.length; i++) {
        allSlugs.add(parts.slice(0, i).join("/"));
      }
    }
    const nodes = new Map<string, FoldoutTreeNode>();
    for (const slug of allSlugs) {
      const c = bySlug.get(slug);
      nodes.set(slug, {
        slug,
        leafName: slug.split("/").pop() ?? slug,
        isCollection: !!c,
        /* Transitive count: a parent collection's badge sums in every
         * descendant collection's members (deduplicated). Matches the
         * filtering rule in library.applyFilter so the badge equals
         * the number of papers that show up when this row is selected. */
        count: c ? membersOf(slug).size : 0,
        children: [],
      });
    }
    const roots: FoldoutTreeNode[] = [];
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

  /** Auto-expand the active collection's ancestors so it's visible in
   *  the fold-out without manual digging when the fold-out is opened. */
  $effect(() => {
    const sel = libraryState.selectedCollection;
    if (!sel || !collectionsFoldoutOpen) return;
    const next = new Set(foldoutExpanded);
    const parts = sel.split("/");
    for (let i = 1; i < parts.length; i++) {
      next.add(parts.slice(0, i).join("/"));
    }
    if (next.size !== foldoutExpanded.size) foldoutExpanded = next;
  });

  /** Keep the Inbox count badge fresh in the reading-mode fold-out.
   *  Refresh once on mount and again whenever the library changes
   *  (a successful file_paper.py run pulls a PDF out of Inbox). */
  void refreshInbox();

  /** Drop-target tracking for the fold-out tree: dragging a library row
   *  onto a collection node here adds the paper(s) to that collection
   *  (same as the organize-view drop), so users get a quick "add to
   *  folder" affordance without leaving reading mode. The payload uses
   *  the same MIME types the organize-view emits. */
  let foldoutDropTargetSlug = $state<string | null>(null);
  async function onFoldoutDrop(
    e: DragEvent,
    slug: string,
    isCollection: boolean,
  ) {
    e.preventDefault();
    foldoutDropTargetSlug = null;
    if (!isCollection) {
      toast("Can't drop into a container — only into a collection.", "error");
      return;
    }
    const multi = e.dataTransfer?.getData("application/x-vault-citekeys");
    const single =
      e.dataTransfer?.getData("application/x-vault-citekey") ||
      e.dataTransfer?.getData("text/plain");
    const ckList = multi
      ? multi.split("\n").filter(Boolean)
      : single
        ? [single]
        : [];
    if (ckList.length === 0) return;
    let ok = 0;
    let fail = 0;
    for (const ck of ckList) {
      try {
        await addPaperToCollection(slug, ck);
        ok++;
      } catch {
        fail++;
      }
    }
    if (fail === 0) toast(`Added ${ok} → ${slug}`);
    else toast(`Added ${ok}, failed ${fail}`, "error");
  }

  $effect(() => {
    void tabsState.searchFocusToken;
    searchInput?.focus();
    searchInput?.select();
  });

  const filtered = $derived.by(() => {
    // Semantic search produces its own rank order; respect it.
    if (libraryState.searchMode === "semantic" && libraryState.query.trim()) {
      return semanticPapers();
    }
    return applyFilter(libraryState.papers);
  });

  /** Look up the last-opened timestamp for a paper if it's in recents, else
   *  null. Used to render "X ago" when the user sorts by `opened`. */
  function recentlyOpenedAt(citekey: string): number | null {
    const r = prefsState.recents.find((r) => r.citekey === citekey);
    return r ? r.at : null;
  }

  function relativeTime(at: number): string {
    if (!at) return "";
    const diff = Date.now() - at;
    if (diff < 60_000) return "just now";
    if (diff < 60 * 60_000) return `${Math.floor(diff / 60_000)} min ago`;
    if (diff < 24 * 60 * 60_000) return `${Math.floor(diff / (60 * 60_000))} hr ago`;
    const days = Math.floor(diff / (24 * 60 * 60_000));
    if (days < 7) return `${days} d ago`;
    const weeks = Math.floor(days / 7);
    if (weeks < 5) return `${weeks} wk ago`;
    return new Date(at).toISOString().slice(0, 10);
  }
  /** Parse the frontmatter `added` field. Bare `YYYY-MM-DD` is treated as
   *  local-noon to avoid timezone drift labelling something added today as
   *  yesterday. ISO datetimes (with time + offset) parse natively. */
  function parseAddedTs(iso: string): number {
    if (!iso) return 0;
    const t = Date.parse(iso);
    if (!Number.isNaN(t)) {
      // If the string had no time component, Date.parse treats it as UTC
      // midnight which can shift across timezone boundaries; nudge to local
      // noon for stable day labelling.
      if (/^\d{4}-\d{2}-\d{2}$/.test(iso.trim())) return t + 12 * 60 * 60_000;
      return t;
    }
    return 0;
  }

  /** Relative time for ISO timestamps in the `added` field. Sub-day units
   *  (minutes, hours) when the source includes time-of-day; otherwise day
   *  resolution. Falls back to the raw ISO string if unparseable. */
  function relativeDateTime(iso: string): string {
    if (!iso) return "";
    const t = parseAddedTs(iso);
    if (!t) return iso;
    const hasTime = /T\d{2}:\d{2}/.test(iso);
    const diff = Date.now() - t;
    if (hasTime) {
      if (diff < 60_000) return "just now";
      if (diff < 60 * 60_000) return `${Math.floor(diff / 60_000)} min ago`;
      if (diff < 24 * 60 * 60_000) return `${Math.floor(diff / (60 * 60_000))} hr ago`;
    }
    const days = Math.floor(diff / (24 * 60 * 60_000));
    if (days <= 0) return hasTime ? "today" : "today";
    if (days === 1) return "yesterday";
    if (days < 7) return `${days} d ago`;
    const weeks = Math.floor(days / 7);
    if (weeks < 5) return `${weeks} wk ago`;
    return iso.slice(0, 10);
  }
  /** "Now" tick so relative times update without a manual refresh. Updated
   *  every minute via $effect; reading it makes filtered re-derive. */
  let nowTick = $state(Date.now());
  $effect(() => {
    const id = setInterval(() => (nowTick = Date.now()), 60_000);
    return () => clearInterval(id);
  });

  // Trigger a new semantic search whenever the query changes in semantic mode.
  $effect(() => {
    void libraryState.query;
    void libraryState.searchMode;
    scheduleSemanticSearch();
  });

  const semanticAvailable = $derived(libraryState.embedHealth?.ok === true);

  function rowClick(e: MouseEvent, citekey: string): void {
    if (e.metaKey || e.ctrlKey || e.button === 1) openInNewTab(citekey);
    else openInTab(citekey);
  }

  /** Concatenate BibTeX for the given citekeys via the Rust command, copy
   *  the result to the clipboard, and toast a one-line confirmation. */
  async function copyBibtex(citekeys: string[], hint: string): Promise<void> {
    if (citekeys.length === 0) return;
    try {
      const bib = await readBibtex(citekeys);
      // Use Tauri's clipboard plugin — navigator.clipboard.writeText fails
      // with NotAllowedError in WKWebView outside trusted user-gesture paths.
      await clipboardWriteText(bib);
      const n = citekeys.length;
      toast(`Copied ${n} BibTeX entr${n === 1 ? "y" : "ies"} — ${hint}`);
    } catch (e) {
      toast(`Copy BibTeX failed: ${e}`, "error");
    }
  }

  function copyVisibleBibtex(): void {
    const ck = filtered.map((p) => p.citekey);
    void copyBibtex(ck, ck.length === libraryState.papers.length ? "all" : "filtered");
  }

  function rowContextMenu(e: MouseEvent, p: { citekey: string }): void {
    e.preventDefault();
    openCtxMenu(e.clientX, e.clientY, paperRowMenu(p.citekey));
  }

  // Drag-resize the library width via a 4px handle on the right edge.
  let resizing = $state(false);
  function startResize(e: MouseEvent) {
    e.preventDefault();
    resizing = true;
    const startX = e.clientX;
    const startW = prefsState.libraryWidth;
    function move(ev: MouseEvent) {
      const dx = ev.clientX - startX;
      prefsState.libraryWidth = Math.max(180, Math.min(600, startW + dx));
    }
    function up() {
      resizing = false;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }
</script>

<aside class="library">
  <!-- 56px top strip — traffic-light clearance (--tl-pad) on the left,
       then the Reading/Organizing view-switch as the very first child.
       This matches the organize overlay's top-strip exactly, so the
       ViewSwitch lands on the same screen (x, y) regardless of mode —
       the cursor doesn't move when the user flips between them. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="top-strip"
    data-tauri-drag-region
    onmousedown={onStripMouseDown}>
    <ViewSwitch active="reading" />
  </div>
  <header class="masthead">
    <div class="caps">
      <span>The Vault</span>
      <span class="dot">·</span>
      <span>No. {String(libraryState.papers.length).padStart(3, "0")}</span>
    </div>
    <h1 class="title">
      <span class="bold">Literature</span>
      <span class="italic">collected.</span>
    </h1>
    {#if vaultPath}
      <p class="vault-path" title={vaultPath}>{vaultPath}</p>
    {/if}
    <div class="search-row">
      <span class="search-icon" aria-hidden="true">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="5.5" cy="5.5" r="4" />
          <path d="M8.5 8.5l3 3" stroke-linecap="round" />
        </svg>
      </span>
      <input
        type="search"
        placeholder="Search the collection…"
        bind:this={searchInput}
        bind:value={libraryState.query}
      />
      <button
        class="sem-toggle"
        role="switch"
        aria-checked={libraryState.searchMode === "semantic"}
        aria-label="Semantic search"
        title={semanticAvailable
          ? "Semantic search — meaning over keywords"
          : (libraryState.embedHealth?.error
              ? `embed server unreachable: ${libraryState.embedHealth.error}`
              : "embed server unreachable")}
        disabled={!semanticAvailable}
        class:on={libraryState.searchMode === "semantic"}
        onclick={() => setSearchMode(libraryState.searchMode === "semantic" ? "metadata" : "semantic")}
      >
        <span class="sem-label">SEM</span>
        <span class="sem-track" aria-hidden="true">
          <span class="sem-thumb"></span>
        </span>
      </button>
    </div>
    {#if libraryState.searchMode === "semantic"}
      <div class="sem-status caps">
        {#if libraryState.semanticError}
          <span class="err">error: {libraryState.semanticError}</span>
        {:else if libraryState.semanticWarming}
          <span>warming…</span>
        {:else if libraryState.semanticLoading}
          <span>searching…</span>
        {:else if libraryState.semanticResults}
          <span>{libraryState.semanticResults.length} ranked</span>
        {/if}
      </div>
    {/if}
  </header>

  <!-- Tag chip strip — discoverable surface for the tag filter. Default
       collapsed to one row; "more" expands to a scrollable grid. Clicking
       a chip toggles it as a filter; active chips render in the accent fill. -->
  {#if allTags().length > 0}
    {@const allKnownTags = allTags()}
    <div class="tag-strip" class:expanded={tagsExpanded}>
      <button
        class="tag-strip-toggle"
        onclick={() => (tagsExpanded = !tagsExpanded)}
        title={tagsExpanded ? "Collapse tags" : "Expand all tags"}>
        Tags <span class="caret">{tagsExpanded ? "▴" : "▾"}</span>
      </button>
      <div class="tag-chips">
        {#each allKnownTags as t (t)}
          <button
            class="tag-chip"
            class:on={libraryState.selectedTags.includes(t)}
            class:cite={t.startsWith("cite:")}
            onclick={() => toggleTagFilter(t)}
            title={`Toggle "${t}" as filter`}>{t.replace(/^cite:/, "")}</button>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Collections fold-out — read-only browse over the tree. Header
       always visible (collapsed reads "in · all papers"); click anywhere
       on the header to expand and the tree drops down beneath it. The
       only entry point into editing is the Reading/Organizing switch in
       the top strip — drag, rename and delete only live in Organize. -->
  <div class="collections-foldout" class:open={collectionsFoldoutOpen}>
    <button
      class="cf-header"
      onclick={() => (collectionsFoldoutOpen = !collectionsFoldoutOpen)}
      title={collectionsFoldoutOpen ? "Hide collections" : "Show collections"}
    >
      <span class="cf-caret" class:open={collectionsFoldoutOpen}>▾</span>
      <span class="cf-caps">in</span>
      <span class="cf-name">
        {libraryState.selectedCollection ?? "all papers"}
      </span>
      <span class="cf-spacer"></span>
      <span class="cf-count mono">
        {libraryState.selectedCollection
          ? membersOf(libraryState.selectedCollection).size
          : libraryState.papers.length}
      </span>
    </button>
    {#if collectionsFoldoutOpen}
      <div class="cf-body">
        <!-- Inbox pseudo-row sits at the top: it's not a subset of
             "all papers" (it's unfiled PDFs that aren't in the library
             yet), so listing it above keeps the hierarchy honest —
             everything below is a view onto the filed corpus.
             Clicking flips the app into Organizing mode and the
             Collections panel auto-switches to the inbox view, so
             the unfiled-papers list is one click away from the reader. -->
        <button
          class="cf-row all-row cf-inbox-row"
          class:has-items={inboxState.items.length > 0}
          onclick={() => {
            prefsState.viewMode = "organize";
            requestOpenInbox();
          }}
          title="Open the Inbox in Organizing view">
          <span class="cf-icon mono">⌬</span>
          <span class="cf-leaf">inbox</span>
          <span class="cf-jumphint">→ organizing</span>
          <span class="cf-c mono">{inboxState.items.length}</span>
        </button>

        <button
          class="cf-row all-row"
          class:active={!libraryState.selectedCollection}
          onclick={() => setCollectionFilter(null)}>
          <span class="cf-icon mono">∀</span>
          <span class="cf-leaf">all papers</span>
          <span class="cf-c mono">{libraryState.papers.length}</span>
        </button>

        {#each foldoutTree as node (node.slug)}
          {@render FoldoutNode(node, 0)}
        {/each}
      </div>
    {/if}
  </div>

  {#snippet FoldoutNode(node: { slug: string; leafName: string; isCollection: boolean; count: number; children: typeof foldoutTree }, depth: number)}
    {@const isOpen = foldoutExpanded.has(node.slug)}
    {@const isActive = libraryState.selectedCollection === node.slug}
    <!-- The data-drop-target-slug attribute opts this node into the
         Tauri OS-routed drop handler in App.svelte (the live path on
         macOS — WKWebView swallows the HTML5 events). The ondragover /
         ondrop on this element are kept as a fallback. -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="cf-row-wrap"
      style="--depth: {depth};"
      class:active={isActive}
      class:drop-target={node.isCollection && (foldoutDropTargetSlug === node.slug || dndState.hoverSlug === node.slug)}
      data-drop-target-slug={node.isCollection ? node.slug : null}
      ondragover={(e) => {
        if (!node.isCollection) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        foldoutDropTargetSlug = node.slug;
      }}
      ondragleave={() => {
        if (foldoutDropTargetSlug === node.slug) foldoutDropTargetSlug = null;
      }}
      ondrop={(e) => onFoldoutDrop(e, node.slug, node.isCollection)}>
      <button
        class="cf-caret-btn"
        class:invisible={node.children.length === 0}
        onclick={() => toggleFoldoutExpand(node.slug)}
        aria-label={isOpen ? "Collapse" : "Expand"}
        >{isOpen ? "▾" : "▸"}</button>
      <button
        class="cf-leaf-btn"
        disabled={!node.isCollection}
        onclick={() => node.isCollection && setCollectionFilter(node.slug)}>
        <span class="cf-icon serif">{node.isCollection ? "/" : "◆"}</span>
        <span class="cf-leaf" class:group-name={!node.isCollection}>
          {node.leafName}
        </span>
        <span class="cf-c mono">{node.count}</span>
      </button>
    </div>
    {#if isOpen}
      {#each node.children as child (child.slug)}
        {@render FoldoutNode(child, depth + 1)}
      {/each}
    {/if}
  {/snippet}

  {#if libraryState.selectedTags.length > 0 || libraryState.selectedCollection}
    <div class="active-filters">
      <span class="active-filters-label">Filtering by</span>
      {#if libraryState.selectedCollection}
        <button
          class="filter-chip collection"
          onclick={() => setCollectionFilter(null)}
          title={`Remove the collection filter`}
        >
          <span>{libraryState.selectedCollection}</span>
          <span class="x" aria-hidden="true">×</span>
        </button>
      {/if}
      {#each libraryState.selectedTags as t (t)}
        <button
          class="filter-chip"
          class:cite={t.startsWith("cite:")}
          onclick={() => toggleTagFilter(t)}
          title={`Remove "${t}" from the filter`}
        >
          <span>{t}</span>
          <span class="x" aria-hidden="true">×</span>
        </button>
      {/each}
      <button
        class="clear-filters"
        onclick={() => {
          clearTagFilter();
          setCollectionFilter(null);
        }}
        title="Clear all filters">clear</button>
    </div>
  {/if}

  <div class="sort caps">
    <label>
      <span>Sorted</span>
      <span class="dot">·</span>
      <select bind:value={libraryState.sortKey}>
        <option value={"opened" as SortKey}>opened</option>
        <option value={"added" as SortKey}>added</option>
        <option value={"year" as SortKey}>year</option>
        <option value={"journal" as SortKey}>journal</option>
        <option value={"title" as SortKey}>title</option>
      </select>
    </label>
    <button
      class="dir"
      onclick={() => (libraryState.sortDir = libraryState.sortDir === "asc" ? "desc" : "asc")}
      title="Toggle sort direction"
    >{libraryState.sortDir === "asc" ? "↑" : "↓"}</button>
    <span class="meta">{filtered.length} / {libraryState.papers.length}</span>
    <button
      class="copy-bib"
      onclick={copyVisibleBibtex}
      title={filtered.length === libraryState.papers.length
        ? `Copy BibTeX for all ${filtered.length} entries to the clipboard`
        : `Copy BibTeX for the ${filtered.length} visible entries to the clipboard`}
      disabled={filtered.length === 0}
    >Copy bib</button>
  </div>

  {#if libraryState.loadError}
    <div class="error">Failed: {libraryState.loadError}</div>
  {:else if libraryState.papers.length === 0 && libraryState.loading}
    <div class="muted">Loading…</div>
  {:else}
    <ul>
      {#each filtered as p (p.citekey)}
        {@const lastName = (p.authors[0] ?? "").split(",")[0].trim()}
        {@const isManuscript = p.tags.some((t) => t.startsWith("cite:"))}
        <li class:active={tabsState.tabs[tabsState.activeIndex]?.citekey === p.citekey}>
          <button
            draggable="true"
            ondragstart={(e) => {
              if (!e.dataTransfer) return;
              e.dataTransfer.setData("application/x-vault-citekey", p.citekey);
              e.dataTransfer.setData("text/plain", p.citekey);
              e.dataTransfer.effectAllowed = "copy";
              startInternalDrag([p.citekey]);
            }}
            ondragend={(e) => void finishInternalDrag(e)}
            onclick={(e) => rowClick(e, p.citekey)}
            ondblclick={() => openInNewTab(p.citekey)}
            onmousedown={(e) => {
              if (e.button === 1) {
                e.preventDefault();
                openInNewTab(p.citekey);
              }
            }}
            oncontextmenu={(e) => rowContextMenu(e, p)}
          >
            <div class="row-byline">
              <span class="row-author-italic">{lastName}</span>
              <span class="row-dot">·</span>
              <span class="row-year">{p.year}</span>
              <span class="row-byline-spacer"></span>
              {#if libraryState.sortKey === "opened"}
                {@const ts = recentlyOpenedAt(p.citekey)}
                {#if ts}
                  <span class="row-recent-ago" title={new Date(ts).toLocaleString()}>
                    {void nowTick, relativeTime(ts)}
                  </span>
                {/if}
              {:else if libraryState.sortKey === "added" && p.added}
                <span class="row-recent-ago" title={`added ${p.added}`}>
                  {void nowTick, relativeDateTime(p.added)}
                </span>
              {/if}
              {#if isManuscript}<span class="row-bullet" aria-hidden="true">●</span>{/if}
            </div>
            <div class="row-title">{p.title}</div>
            {#if p.journal}
              <div class="row-journal">{p.journal}</div>
            {/if}
          </button>
        </li>
      {/each}
      {#if filtered.length === 0}
        <li class="empty caps">no matches</li>
      {/if}
    </ul>
  {/if}

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="resize-handle" class:active={resizing} onmousedown={startResize} role="separator" aria-orientation="vertical" tabindex="-1"></div>
</aside>

<style>
  aside.library {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background: var(--panel);
    min-width: 0;
    position: relative;
  }

  /* 56px top strip — clears the macOS traffic lights with --tl-pad on
     the left and houses the Reading/Organizing segmented switch. Same
     shape in the Organize overlay, anchored at identical screen
     coordinates. Window drag is wired in JS via the onmousedown
     handler above (data-tauri-drag-region alone wasn't firing — see
     the comment on onStripMouseDown). */
  .top-strip {
    flex: 0 0 auto;
    height: 56px;
    padding: 0 22px 0 var(--tl-pad);
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid var(--ink-12);
  }
  /* Masthead — "THE VAULT · NO. 102" + "Literature collected." + search.
     Sizes lifted from B_LeftPane in direction-b.jsx. */
  .masthead {
    flex: 0 0 auto;
    padding: 12px 22px 0;
  }
  .masthead .caps {
    color: var(--accent);
    margin-bottom: 4px;
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  .masthead .caps .dot {
    color: var(--accent);
    font-weight: 400;
    margin: 0 4px;
  }
  .masthead .title {
    font-family: var(--serif);
    font-size: 26px;
    font-weight: 400;
    line-height: 1;
    margin: 0;
    color: var(--ink);
    letter-spacing: -0.6px;
  }
  .masthead .title .bold {
    font-weight: 700;
    display: block;
    line-height: 1;
  }
  .masthead .title .italic {
    font-style: italic;
    font-weight: 400;
    display: block;
    color: var(--accent);
    line-height: 1.05;
  }
  /* Active-vault path beneath the masthead title. Truncated from the front
     (direction: rtl + unicode-bidi: plaintext) so the meaningful end of the
     path — the vault folder name — stays visible when it overflows. */
  .masthead .vault-path {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--ink-50);
    margin: 6px 0 0;
    padding: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    direction: rtl;
    text-align: left;
    unicode-bidi: plaintext;
  }

  /* Search row — direction-b.jsx wraps it in `<div padding='0 22px 14px'>`
     and the search line itself is height 36 with a 1.5px ink bottom rule. */
  .search-row {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 36px;
    border-bottom: 1.5px solid var(--ink);
    padding: 0 0 0 2px;
    margin: 16px 0 14px;
  }
  .search-icon {
    display: flex;
    align-items: center;
    color: var(--ink-70);
    width: 13px;
    flex-shrink: 0;
  }
  .search-icon svg {
    display: block;
  }
  .search-row input {
    flex: 1;
    min-width: 0;
    border: 0;
    background: transparent;
    padding: 0;
    font-family: var(--serif);
    font-style: italic;
    font-size: 13px;
    color: var(--ink);
  }
  .search-row input::placeholder {
    color: var(--ink-50);
    font-style: italic;
    font-family: var(--serif);
  }
  .search-row input:focus {
    outline: none;
  }
  /* Semantic search toggle — labeled iOS-style switch.
     Off: muted label, gray track, thumb at left.
     On: accent label, accent track, thumb slid right. */
  .sem-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 0;
    background: transparent;
    padding: 0;
    cursor: pointer;
    align-self: center;
    color: var(--ink-50);
  }
  .sem-toggle:hover:not(:disabled) {
    color: var(--ink);
  }
  .sem-toggle.on {
    color: var(--accent);
  }
  .sem-toggle:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sem-label {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
  }
  .sem-track {
    position: relative;
    width: 22px;
    height: 12px;
    background: var(--ink-12);
    border-radius: 6px;
    transition: background 0.15s ease;
    flex-shrink: 0;
  }
  .sem-toggle:hover:not(:disabled) .sem-track {
    background: var(--ink-30);
  }
  .sem-toggle.on .sem-track,
  .sem-toggle.on:hover:not(:disabled) .sem-track {
    background: var(--accent);
  }
  .sem-thumb {
    position: absolute;
    top: 1px;
    left: 1px;
    width: 10px;
    height: 10px;
    background: var(--panel);
    border-radius: 50%;
    box-shadow: 0 0.5px 1px rgba(0, 0, 0, 0.2);
    transition: transform 0.15s ease;
  }
  .sem-toggle.on .sem-thumb {
    transform: translateX(10px);
  }
  .sem-status {
    margin-top: 6px;
    padding: 0 22px;
  }
  .sem-status .err {
    color: var(--accent);
  }

  /* Tag chip strip — discoverable filter surface. Default: collapsed to a
     single horizontally-scrollable row. Expanded: multi-row wrap. */
  .tag-strip {
    flex: 0 0 auto;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px;
    align-items: center;
    padding: 6px 22px 8px;
    border-bottom: 1px solid var(--ink-07);
  }
  .tag-strip-toggle {
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    cursor: pointer;
    padding: 0;
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .tag-strip-toggle:hover {
    color: var(--ink);
  }
  .tag-strip-toggle .caret {
    color: var(--ink-30);
    font-size: 9px;
  }
  .tag-chips {
    display: flex;
    flex-wrap: nowrap;
    gap: 4px;
    overflow-x: auto;
    align-items: center;
    /* Hide scrollbar to keep the strip clean — wheel/swipe still scrolls. */
    scrollbar-width: none;
  }
  .tag-chips::-webkit-scrollbar {
    display: none;
  }
  .tag-strip.expanded .tag-chips {
    flex-wrap: wrap;
    overflow-x: visible;
    max-height: 40vh;
    overflow-y: auto;
  }
  .tag-chip {
    border: 0.5px solid var(--ink-30);
    background: transparent;
    padding: 1px 7px;
    border-radius: 0;
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 500;
    line-height: 1.4;
    color: var(--ink-70);
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .tag-chip:hover {
    background: var(--accent-soft);
  }
  .tag-chip.on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--panel);
  }
  .tag-chip.cite {
    border-style: dashed;
  }

  /* Collections fold-out — collapsible read-only tree. Header always
     visible (current selection labelled "in · …"); body slides open
     beneath it when expanded, lifting the section to a whiter panel
     so it reads as the active control among the sidebar's strata. */
  .collections-foldout {
    flex: 0 0 auto;
    border-top: 1px solid var(--ink-12);
  }
  .collections-foldout.open {
    background: var(--panel);
  }
  .cf-header {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 22px;
    border: 0;
    background: transparent;
    cursor: pointer;
    color: inherit;
    text-align: left;
    border-radius: 0;
  }
  .cf-header:hover {
    color: var(--accent);
  }
  .cf-caret {
    width: 10px;
    color: var(--ink-50);
    font-size: 9px;
    transform: rotate(-90deg);
    transition: transform 120ms;
  }
  .cf-caret.open {
    transform: none;
  }
  .cf-caps {
    font-family: var(--sans);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-50);
  }
  .cf-name {
    font-family: var(--serif);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: -0.2px;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 0 1 auto;
  }
  .cf-spacer {
    flex: 1;
  }
  .cf-count {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-30);
    font-variant-numeric: tabular-nums;
  }
  .cf-body {
    border-top: 1px solid var(--ink-07);
    padding: 4px 0 10px;
  }
  .cf-row,
  .cf-row-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 14px 5px calc(10px + var(--depth, 0) * 14px);
    border-left: 2px solid transparent;
    width: 100%;
    background: transparent;
    border: 0;
    color: inherit;
    text-align: left;
    cursor: pointer;
    border-radius: 0;
    font: inherit;
    height: 26px;
  }
  .cf-row.active,
  .cf-row-wrap.active {
    background: var(--panel-alt);
    border-left-color: var(--accent);
  }

  /* Inbox pseudo-row — same shape as "all papers" but distinctly
     styled. The leaf name is set in a smaller mono caps face so it
     reads as a special destination rather than a regular collection.
     The count badge turns burnt umber when there are unfiled PDFs so
     the user notices something is waiting. */
  .cf-inbox-row .cf-icon {
    color: var(--ink-30);
  }
  .cf-inbox-row .cf-leaf {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--ink-70);
  }
  .cf-inbox-row.has-items .cf-icon,
  .cf-inbox-row.has-items .cf-leaf,
  .cf-inbox-row.has-items .cf-c {
    color: var(--accent);
  }
  /* Tells the user the click switches to Organizing view. Sits between
     the "inbox" label and the count badge; pushes the count to the
     right edge so the row reads "⌬ inbox → organizing       N". */
  .cf-inbox-row .cf-jumphint {
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 500;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--ink-50);
    margin-right: auto;
  }
  .cf-inbox-row.has-items .cf-jumphint {
    color: var(--accent);
    opacity: 0.7;
  }
  /* Drop target highlight — dashed accent border-left + faint accent
     wash. Visible while a library row is being dragged over a
     collection node in the fold-out tree; on drop, the paper is added
     to that collection. */
  .cf-row-wrap.drop-target {
    background: rgba(122, 58, 20, 0.10);
    border-left: 2px dashed var(--accent);
  }
  .cf-row.all-row {
    padding-left: 24px;
  }
  .cf-caret-btn {
    width: 14px;
    height: 14px;
    line-height: 14px;
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-size: 9px;
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
  }
  .cf-caret-btn.invisible {
    visibility: hidden;
  }
  .cf-leaf-btn {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px;
    border: 0;
    background: transparent;
    color: var(--ink);
    font-family: var(--serif);
    font-size: 12.5px;
    cursor: pointer;
    overflow: hidden;
    text-align: left;
  }
  .cf-leaf-btn:hover:not(:disabled) {
    color: var(--accent);
  }
  .cf-leaf-btn:disabled {
    cursor: default;
    color: var(--ink-50);
  }
  .cf-icon {
    width: 12px;
    text-align: center;
    color: var(--ink-50);
    font-size: 10px;
    flex-shrink: 0;
  }
  .cf-icon.serif {
    font-family: var(--serif);
    font-style: italic;
  }
  .cf-leaf {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cf-leaf.group-name {
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--ink-70);
  }
  .cf-c {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-30);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  .filter-chip.collection {
    font-family: var(--mono);
  }

  /* Active tag filters — chips next to / under the search bar so the user
     can see what's narrowing the list and dismiss individual filters. */
  .active-filters {
    flex: 0 0 auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 8px 22px 10px;
    border-bottom: 1px solid var(--ink-07);
  }
  .active-filters-label {
    font-family: var(--sans);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--ink-50);
    margin-right: 2px;
  }
  .filter-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 0;
    background: var(--accent);
    color: var(--panel);
    padding: 2px 4px 2px 8px;
    border-radius: 1px;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 500;
    cursor: pointer;
  }
  .filter-chip:hover {
    background: var(--accent-bright);
  }
  .filter-chip .x {
    font-family: var(--sans);
    font-size: 13px;
    line-height: 1;
    padding: 0 2px;
  }
  .clear-filters {
    border: 0;
    background: transparent;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    cursor: pointer;
    padding: 0 4px;
  }
  .clear-filters:hover {
    color: var(--accent);
  }

  /* Section nav — ALL · RECENT · TAGS · MANUSCRIPTS.
     Per direction-b.jsx: padding 6px 22px 10px, gap 14, Inter 10px 600,
     letter-spacing 1.4, uppercase. Active gets 1.5px solid accent
     border-bottom with paddingBottom 4. */

  /* Sort caption — direction-b.jsx: padding 6px 22px 8px, flex justify
     between, border-top 1px solid INK (heavy!), border-bottom 1px solid
     ink07. "Sorted · added ↓" Inter 9px ink50 letter-spacing 1.4 caps 600.
     "102 / 102" JetBrainsMono 9.5px ink70 tabular-nums. */
  .sort {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    padding: 6px 22px 8px;
    border-top: 1px solid var(--ink);
    border-bottom: 1px solid var(--ink-07);
  }
  .sort label {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-family: var(--sans);
    font-size: 9px;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    font-weight: 600;
    color: var(--ink-50);
  }
  .sort .dot {
    color: var(--ink-30);
    font-weight: 400;
  }
  .sort select {
    font-family: var(--sans);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    font-weight: 600;
    padding: 0;
    background: transparent;
    color: var(--ink-50);
    border: 0;
    cursor: pointer;
    appearance: none;
    -webkit-appearance: none;
  }
  .sort .dir {
    border: 0;
    background: transparent;
    padding: 0;
    cursor: pointer;
    color: var(--ink);
    font-size: 11px;
    line-height: 1;
  }
  .sort .meta {
    font-family: var(--mono);
    font-size: 9.5px;
    color: var(--ink-70);
    font-variant-numeric: tabular-nums;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    margin-left: auto;
  }
  .sort .copy-bib {
    border: 1px solid var(--ink-12);
    background: transparent;
    padding: 1px 8px;
    border-radius: 1px;
    font-family: var(--sans);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 600;
    color: var(--ink-50);
    cursor: pointer;
  }
  .sort .copy-bib:hover:not(:disabled) {
    background: var(--accent-soft);
    color: var(--accent);
    border-color: var(--accent);
  }

  /* Paper list */
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    overflow-y: auto;
    flex: 1 1 auto;
    background: var(--surface);
  }
  li {
    border-bottom: 1px solid var(--border);
  }
  li.empty {
    padding: 32px 28px;
    color: var(--muted);
    text-align: center;
    font-size: 9.5px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    font-weight: 600;
  }
  /* Paper row — direction-b.jsx B_ListRow:
     padding 11px 22px (compact: 8px), border-bottom 1px ink07,
     border-left 2px (active=accent, unread=accent, else transparent),
     bg active = panelAlt. */
  li button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 11px 22px;
    cursor: pointer;
    border-radius: 0;
    border-left: 2px solid transparent;
    margin-left: 0;
    position: relative;
    box-sizing: border-box;
  }
  li button:hover {
    background: var(--hover);
  }
  li.active button {
    border-left-color: var(--accent);
    background: var(--panel-alt);
  }
  /* Byline — Inter 10.5px, letter-spacing 0.1, ink50 weight 500.
     Author becomes accent on active. */
  .row-byline {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-family: var(--sans);
    font-size: 10.5px;
    letter-spacing: 0.1px;
    color: var(--ink-50);
    font-weight: 500;
    margin-bottom: 3px;
  }
  .row-byline .row-author-italic {
    color: var(--ink-70);
    font-weight: 600;
    font-style: normal;
  }
  li.active .row-byline .row-author-italic {
    color: var(--accent);
  }
  .row-byline .row-dot {
    color: var(--ink-30);
  }
  .row-byline .row-year {
    font-variant-numeric: tabular-nums;
    color: var(--ink-50);
  }
  .row-byline .row-bullet {
    color: var(--ink-30);
    font-size: 4px;
    line-height: 1;
    transform: translateY(-2px);
  }
  .row-byline-spacer {
    flex: 1;
  }
  .row-byline .row-recent-ago {
    font-family: var(--mono);
    font-size: 9.5px;
    color: var(--ink-30);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0;
  }
  /* Title — Source Serif 14px (compact 13px), weight 500 (600 active),
     line-height 1.3, ellipsis, letter-spacing -0.2. */
  .row-title {
    font-family: var(--serif);
    font-size: 14px;
    font-weight: 500;
    line-height: 1.3;
    color: var(--ink);
    margin-bottom: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    letter-spacing: -0.2px;
  }
  li.active .row-title {
    font-weight: 600;
  }
  /* Journal — Source Serif italic 11px ink50, ellipsis. */
  .row-journal {
    font-family: var(--serif);
    font-style: italic;
    font-size: 11px;
    color: var(--ink-50);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .error {
    color: var(--accent);
    padding: 16px;
  }
  .muted {
    color: var(--muted);
    padding: 16px;
  }

  .resize-handle {
    position: absolute;
    top: 0;
    right: -2px;
    bottom: 0;
    width: 4px;
    cursor: col-resize;
    z-index: 5;
  }
  .resize-handle.active,
  .resize-handle:hover {
    background: var(--accent);
  }
</style>

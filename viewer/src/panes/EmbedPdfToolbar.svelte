<!--
  Our minimal PDF toolbar over the headless EmbedPDF API. Same shape as
  the legacy PDFView toolbar (PREV / 1/15 NEXT, FIT − +, FIND ⌘F) but
  drives the EmbedPDF plugins instead of pdfjs directly.

  Lives next to EmbedPDFView so it can read `documentId` as a prop and
  call `useZoom(() => documentId)` etc. at script-setup level (the
  hooks expect a reactive getter for documentId, which lets the same
  toolbar instance follow tab switches without remounting).
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { useZoom, ZoomMode } from "@embedpdf/plugin-zoom/svelte";
  import { useScroll } from "@embedpdf/plugin-scroll/svelte";
  import { useSearch } from "@embedpdf/plugin-search/svelte";
  import { useAnnotation } from "@embedpdf/plugin-annotation/svelte";
  import { tabsState } from "../state/tabs.svelte";

  type Props = { documentId: string };
  let { documentId }: Props = $props();

  /* ⌘F / ⌘⇧F are caught by App.svelte's keymap (`makeKeymap`) which calls
   * `requestPdfFindFocus()` — that increments `tabsState.pdfFindFocusToken`.
   * The legacy PDFView listens to this token; we do the same so the
   * shortcut works in the EmbedPDF spike too. Track the last token we
   * handled to avoid re-opening on every state read. */
  let lastFindToken = $state(tabsState.pdfFindFocusToken);
  $effect(() => {
    const t = tabsState.pdfFindFocusToken;
    if (t !== lastFindToken) {
      lastFindToken = t;
      if (!findOpen) toggleFind();
    }
  });

  const zoom = useZoom(() => documentId);
  const scroll = useScroll(() => documentId);
  const annotation = useAnnotation(() => documentId);

  /* The annotation bar is a separate, toggleable strip. Highlights are
   * created post-text-select via the in-PDF selection menu, so the
   * toolbar doesn't need highlight swatches; the only tool surfaced
   * here is the sticky note: activate, then click anywhere on a page
   * to drop a note (its comment editor opens immediately because
   * EmbedPDF's `textComment` tool has `selectAfterCreate: true`). */
  let annotateOpen = $state(false);
  type ToolId = "textComment";
  let activeToolId = $state<ToolId | null>(null);
  function toggleTool(id: ToolId | null) {
    if (id === activeToolId || id === null) {
      activeToolId = null;
      annotation.provides?.setActiveTool(null);
    } else {
      activeToolId = id;
      annotation.provides?.setActiveTool(id);
    }
  }

  /* The textComment tool has `selectAfterCreate: true` but no
   * `deactivateToolAfterCreate`, so after dropping a sticky note the
   * tool stays active. That makes the *next* click on the page drop
   * another sticky — including a click on the just-placed sticky to
   * drag it. Auto-deactivate ourselves: one sticky per activation, so
   * the user can immediately move/edit the new note. Re-click STICKY
   * NOTE to drop another. */
  $effect(() => {
    const provides = annotation.provides;
    if (!provides) return;
    const off = provides.onAnnotationEvent((evt) => {
      if (evt.type !== "create") return;
      const ann = evt.annotation as { type?: number } | undefined;
      if (!ann || ann.type !== 1 /* PdfAnnotationSubtype.TEXT */) return;
      const current = untrack(() => activeToolId);
      if (current !== "textComment") return;
      activeToolId = null;
      provides.setActiveTool(null);
    });
    return () => off?.();
  });

  const search = useSearch(() => documentId);

  /* Page navigation — scroll plugin owns current page + total pages.
   * Reading `scroll.state.{currentPage,totalPages}` directly matches the
   * canonical PageControls example; the state object IS reactive (Svelte 5
   * tracks property access via the proxy the hook returns), so the
   * template re-renders when either field changes. The convenience methods
   * scrollToPreviousPage / scrollToNextPage handle 1..N clamping. */
  function gotoPrev() {
    scroll.provides?.scrollToPreviousPage();
  }
  function gotoNext() {
    scroll.provides?.scrollToNextPage();
  }

  /* Zoom — same fit-width + −/+ semantics our legacy toolbar exposed. */
  const zoomPct = $derived(Math.round((zoom.state.currentZoomLevel ?? 1) * 100));
  function fit() {
    zoom.provides?.requestZoom(ZoomMode.FitPage);
  }
  function zoomIn() {
    zoom.provides?.zoomIn();
  }
  function zoomOut() {
    zoom.provides?.zoomOut();
  }

  /* Find — open/close the search session and forward the query. The
   * actual highlights are drawn by <SearchLayer> on each page. */
  let findOpen = $state(false);
  let findQuery = $state("");
  /* Last query the search engine actually ran for. Lets Enter mean
   * "run search" the first time and "advance to next match" once the
   * results are loaded. */
  let lastQueryRun = $state("");

  /* n/N badge — read straight off the search plugin's state. The plugin
   * keeps `activeResultIndex` 0-based; show 1-based to the user. */
  const matchCount = $derived(search.state.total ?? 0);
  const matchIdx1 = $derived(
    matchCount > 0 ? Math.max(1, (search.state.activeResultIndex ?? -1) + 1) : 0,
  );

  function toggleFind() {
    findOpen = !findOpen;
    if (findOpen) {
      search.provides?.startSearch?.();
    } else {
      closeFind();
    }
  }

  /* Enter behavior:
   *   - If the query has changed (or no search has run yet) → run a fresh
   *     `searchAllPages`, then advance to the first match.
   *   - Otherwise → just advance via `nextResult()`. Same input, repeated
   *     Enters cycle through matches.
   * Shift+Enter calls `previousResult()` regardless. */
  function onEnter(shift: boolean) {
    if (!findQuery.trim()) return;
    if (shift) {
      search.provides?.previousResult?.();
      return;
    }
    if (findQuery !== lastQueryRun) {
      const q = findQuery;
      search.provides
        ?.searchAllPages?.(q)
        .toPromise()
        .then(() => {
          lastQueryRun = q;
          search.provides?.nextResult?.();
        })
        .catch((e) => {
          console.warn("[EmbedPDF] search failed", e);
        });
    } else {
      search.provides?.nextResult?.();
    }
  }
  function findNext() {
    onEnter(false);
  }
  function findPrev() {
    onEnter(true);
  }

  /* When the active match index changes, scroll the page that match is
   * on into view — without changing zoom. Pick top- or bottom-alignment
   * based on whether the target is below or above the current page, so
   * the visual jump is minimised:
   *   target page > current → bottom-align (target appears from below)
   *   target page < current → top-align (target appears from above)
   *   target page == current → no scroll (the in-page highlight is enough)
   */
  /* Scroll-to-match policy (per user spec — minimise jank):
   *   1. Default: top-align the target page (`alignY: 0`). Page top sits
   *      at the viewport top — predictable, no big visual jump between
   *      consecutive matches.
   *   2. Override to bottom-align (`alignY: 100`) ONLY when the match is
   *      so far down the page that top-aligning would leave it off the
   *      visible viewport.
   *
   * We don't scroll on a per-match basis when the target page is already
   * current — the SearchLayer in-page highlight is enough; no jump
   * needed.
   *
   * To know whether top-align would hide the match, compare the match's
   * Y fraction-of-page against the viewport's fraction-of-page. If
   * matchYFraction > viewportYFraction (i.e., the match starts below
   * what would be visible at top-align), switch to bottom-align. */
  $effect(() => {
    const idx = search.state.activeResultIndex ?? -1;
    const results = search.state.results;
    if (idx < 0 || !results || !results[idx]) return;
    const result = results[idx];
    const targetPage = (result.pageIndex ?? 0) + 1;
    const current = untrack(() => scroll.state.currentPage ?? 1);
    if (targetPage === current) return; // already on this page — SearchLayer's highlight is enough

    // Compute the threshold: how much of the page fits in the viewport?
    // pageLayout.height and viewport clientHeight are both in CSS px so
    // their ratio is meaningful. matchY (from result.rects[0].origin.y)
    // and pageLayout.height share the page's local coordinate space
    // — both express "where on this page" in the same units that
    // pdfium reports, so the fraction matchY / pageHeight is what we
    // want to compare against viewportFraction.
    let alignY = 0; // default: top-align the page
    const firstRect = result.rects?.[0];
    const layout = untrack(() => scroll.provides?.getLayout());
    const pageLayout = layout?.virtualItems
      .flatMap((vi) => vi.pageLayouts)
      .find((p) => p.pageNumber === targetPage);

    if (firstRect && pageLayout && pageLayout.height > 0) {
      const matchYFraction =
        (firstRect.origin.y + (firstRect.size?.height ?? 0)) / pageLayout.height;
      /* Threshold ≈ "how much of the page is visible when top-aligned."
       * Without a viewport-vs-page ratio we use 0.85 as a safe proxy: if
       * the match ends in the bottom ~15% of the page, top-aligning is
       * likely to clip it off, so bottom-align instead. The bottom-15%
       * threshold is generous enough that consecutive matches in the
       * same upper-page region don't flip between alignments. */
      if (matchYFraction > 0.85) {
        alignY = 100;
      }
    }

    scroll.provides?.scrollToPage({
      pageNumber: targetPage,
      alignY,
      behavior: "smooth",
    });
  });

  /* Keyboard shortcuts — active when the PDF is shown and focus isn't in
   * an input / textarea / contenteditable (so arrows still move the cursor
   * in the notes editor / search bar / library search).
   *   ArrowLeft  → previous page
   *   ArrowRight → next page
   *   Cmd/Ctrl + = / +  → zoom in
   *   Cmd/Ctrl + -      → zoom out
   *   Cmd/Ctrl + 0      → fit page
   * Up / Down arrows are intentionally NOT intercepted — the viewport is
   * a scrollable container, so the browser's default scroll-by-line works
   * out of the box.
   */
  function isTextInput(el: EventTarget | null): boolean {
    if (!(el instanceof HTMLElement)) return false;
    if (el.isContentEditable) return true;
    const t = el.tagName;
    return t === "INPUT" || t === "TEXTAREA" || t === "SELECT";
  }

  /** True for our own find input, so ⌘F there toggles rather than no-ops. */
  function isOurFindInput(el: EventTarget | null): boolean {
    return el instanceof HTMLInputElement && el.closest(".find-row") !== null;
  }

  function onKeydown(e: KeyboardEvent) {
    /* Escape — always close the find bar if it's open, even from inside
     * the find input itself. Don't preventDefault otherwise (other UI may
     * use Escape to close modals etc.). */
    if (e.key === "Escape" && findOpen) {
      e.preventDefault();
      closeFind();
      return;
    }

    const mod = e.metaKey || e.ctrlKey;

    /* ⌘F — open PDF find, unless focus is in the notes editor / library
     * search / some other text input that has its own ⌘F binding (e.g.
     * CodeMirror's in-editor find). When focus is in our own find input,
     * treat it as toggle (close + re-open is the same as focusing). */
    if (mod && (e.key === "f" || e.key === "F")) {
      if (isOurFindInput(e.target) || !isTextInput(e.target)) {
        e.preventDefault();
        toggleFind();
        return;
      }
      // Focus is in another text input — let that input's own ⌘F handle it.
      return;
    }

    /* The remaining shortcuts are all "PDF-area" actions; bail when the
     * user is typing somewhere so arrows / +/- in text fields don't get
     * hijacked. */
    if (isTextInput(e.target)) return;

    if (mod) {
      switch (e.key) {
        case "+":
        case "=":
          e.preventDefault();
          zoomIn();
          return;
        case "-":
          e.preventDefault();
          zoomOut();
          return;
        case "0":
          e.preventDefault();
          fit();
          return;
      }
      return;
    }
    if (e.shiftKey || e.altKey) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      gotoPrev();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      gotoNext();
    }
  }

  function closeFind() {
    findOpen = false;
    findQuery = "";
    lastQueryRun = "";
    search.provides?.stopSearch?.();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="ep-toolbar-wrap">
  <div class="ep-toolbar">
    <div class="left">
      <button class="btn" onclick={gotoPrev} disabled={(scroll.state.currentPage ?? 1) <= 1}>‹ PREV</button>
      <span class="page-count">
        <span class="mono">{scroll.state.currentPage ?? 1}</span>
        <span class="dim">/</span>
        <span class="mono dim">{scroll.state.totalPages || "…"}</span>
      </span>
      <button class="btn" onclick={gotoNext} disabled={(scroll.state.currentPage ?? 1) >= (scroll.state.totalPages ?? 0)}>NEXT ›</button>

      <span class="sep"></span>

      <button class="btn" onclick={fit} title="Fit page">FIT</button>
      <button class="btn" onclick={zoomOut} title="Zoom out">−</button>
      <button class="btn" onclick={zoomIn} title="Zoom in">+</button>
      <span class="zoom-pct dim">{zoomPct}%</span>
    </div>

    <div class="right">
      <button
        class="btn annotate-toggle"
        class:active={annotateOpen}
        onclick={() => (annotateOpen = !annotateOpen)}
        title="Show / hide annotation tools"
      >
        ANNOTATE
      </button>
      <button class="btn find" class:active={findOpen} onclick={toggleFind}>
        FIND <span class="kbd">⌘F</span>
      </button>
    </div>
  </div>

  <!-- Annotation row — same overlay pattern as the find row so toggling
       doesn't reflow / rescale the PDF below. -->
  {#if annotateOpen}
    <div class="annotate-row">
      <button
        type="button"
        class="btn tool"
        class:active={activeToolId === "textComment"}
        onclick={() => toggleTool("textComment")}
        aria-pressed={activeToolId === "textComment"}
        title="Click on the page to drop a sticky note"
      >
        STICKY NOTE
      </button>
      <button
        class="btn off"
        class:active={activeToolId === null}
        onclick={() => toggleTool(null)}
        title="Turn tools off"
      >
        OFF
      </button>
      <span class="grow"></span>
      <span class="annotate-hint">
        {#if activeToolId === "textComment"}
          Click on the page to drop a sticky note
        {:else}
          To highlight, select text in the document. Pick a tool here to add a sticky note.
        {/if}
      </span>
    </div>
  {/if}

  <!-- Find row floats as an overlay below the toolbar so opening it
       doesn't shrink the PDF viewport (which would otherwise re-fit and
       rescale the page on every open/close). -->
  {#if findOpen}
    <div class="find-row">
      <input
        type="search"
        bind:value={findQuery}
        placeholder="Find in PDF…"
        onkeydown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onEnter(e.shiftKey);
          }
        }}
        autofocus
      />
      <span class="match-count mono" class:dim={matchCount === 0}>
        {#if matchCount > 0}
          {matchIdx1} <span class="dim">/</span> {matchCount}
        {:else if lastQueryRun}
          no matches
        {:else}
          —
        {/if}
      </span>
      <button class="btn" onclick={findPrev} disabled={matchCount === 0}>‹</button>
      <button class="btn" onclick={findNext} disabled={matchCount === 0}>›</button>
    </div>
  {/if}
</div>

<style>
  /* Wrap is `position: relative` so the find-row overlay can anchor to it
     without taking layout space — opening Find no longer shrinks the PDF
     viewport (which previously triggered a re-fit-page rescale). */
  .ep-toolbar-wrap {
    position: relative;
    flex: 0 0 auto;
  }
  .ep-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 5px 10px;
    border-bottom: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    background: var(--backdrop, #fcfaf5);
    font-family: var(--sans, Inter, system-ui, sans-serif);
    font-size: 11px;
    letter-spacing: 0.04em;
    color: var(--ink-70, rgba(26, 22, 18, 0.7));
    /* Keep everything on one line — the narrow PDF column was wrapping
       PREV/NEXT into two-line labels and making the bar look crowded. */
    flex-wrap: nowrap;
    white-space: nowrap;
    overflow-x: auto;
  }
  .left, .right {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: nowrap;
  }
  .btn {
    appearance: none;
    background: transparent;
    border: 0;
    padding: 3px 6px;
    border-radius: 3px;
    font: inherit;
    font-weight: 600;
    text-transform: uppercase;
    color: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn:hover:not(:disabled) { background: var(--hover, rgba(26, 22, 18, 0.05)); color: var(--ink, #1a1612); }
  .btn:disabled { opacity: 0.35; cursor: default; }
  .btn.find { color: var(--ink, #1a1612); }
  .btn.find.active { background: var(--ink, #1a1612); color: var(--backdrop, #fcfaf5); }
  .page-count {
    font-family: var(--serif, "Source Serif 4", Georgia, serif);
    font-size: 13px;
    color: var(--ink, #1a1612);
    text-transform: none;
    letter-spacing: 0;
    padding: 0 4px;
  }
  .page-count .dim, .zoom-pct { color: var(--ink-30, rgba(26, 22, 18, 0.3)); }
  .page-count .dim { margin: 0 3px; }
  .mono { font-family: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace; }
  .sep {
    width: 1px;
    height: 14px;
    background: var(--ink-12, rgba(26, 22, 18, 0.12));
    display: inline-block;
    margin: 0 4px;
  }
  .zoom-pct {
    font-size: 11px;
    padding-left: 4px;
    text-transform: none;
    letter-spacing: 0;
  }
  .annotate-toggle.active {
    background: var(--ink, #1a1612);
    color: var(--backdrop, #fcfaf5);
  }

  /* Floating annotation bar — overlays the PDF area when toggled on,
     so opening it doesn't reflow / re-fit the viewport. */
  .annotate-row {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 9;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-bottom: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    background: var(--panel, #fff);
    box-shadow: 0 2px 8px -2px rgba(26, 22, 18, 0.12);
  }
  .annotate-hint {
    font-family: var(--serif, "Source Serif 4", Georgia, serif);
    font-size: 12px;
    font-style: italic;
    color: var(--ink-50, rgba(26, 22, 18, 0.5));
    text-transform: none;
    letter-spacing: 0;
  }
  .grow { flex: 1; }
  .btn.off {
    font-size: 10px;
    padding: 2px 6px;
    color: var(--ink-50, rgba(26, 22, 18, 0.5));
    margin-left: 4px;
  }
  .btn.off.active {
    background: var(--ink-07, rgba(26, 22, 18, 0.07));
    color: var(--ink, #1a1612);
  }
  .btn.tool { color: var(--ink, #1a1612); }
  .btn.tool.active {
    background: var(--ink, #1a1612);
    color: var(--backdrop, #fcfaf5);
  }
  .kbd {
    font-size: 10px;
    color: var(--ink-50, rgba(26, 22, 18, 0.5));
    margin-left: 4px;
    font-weight: 500;
    letter-spacing: 0.04em;
  }

  .find-row {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border-bottom: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    background: var(--panel, #fff);
    box-shadow: 0 2px 8px -2px rgba(26, 22, 18, 0.12);
  }
  .find-row input {
    flex: 1 1 auto;
    font: inherit;
    font-size: 13px;
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    border-radius: 3px;
    padding: 5px 9px;
    color: var(--ink, #1a1612);
    background: var(--panel, #fff);
  }
  .find-row input:focus { outline: none; border-color: var(--accent, #7a3a14); }
  .find-row .match-count {
    font-size: 12px;
    color: var(--ink, #1a1612);
    padding: 0 6px;
    white-space: nowrap;
    min-width: 4em;
    text-align: center;
  }
  .find-row .match-count.dim {
    color: var(--ink-50, rgba(26, 22, 18, 0.5));
    font-style: italic;
  }
  .find-row .match-count .dim {
    color: var(--ink-30, rgba(26, 22, 18, 0.3));
    margin: 0 2px;
  }
</style>

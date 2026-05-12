<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { TextLayer } from "pdfjs-dist";
  import { loadPdf, pdfUrlFor, type PDFDocumentProxy } from "../lib/pdf";
  import { tabsState, updateActiveTabPdf } from "../state/tabs.svelte";

  let {
    citekey,
    pdfUrl,
    page = 1,
    zoom = "auto" as number | "auto",
  }: {
    /** Library paper to load via vault-side citekey → path resolution.
     *  When pdfUrl is provided this is ignored for loading; it's only
     *  kept for tab-state syncing (so inbox-preview rendering doesn't
     *  try to write back to a tab). */
    citekey?: string;
    /** Direct asset URL — pass when previewing a PDF that isn't in
     *  the library yet (e.g. files sitting in the Inbox). Takes
     *  precedence over `citekey` for loading. */
    pdfUrl?: string;
    page?: number;
    zoom?: number | "auto";
  } = $props();

  let pageList: HTMLDivElement | undefined = $state();
  let doc = $state<PDFDocumentProxy | null>(null);
  let totalPages = $state(0);
  // svelte-ignore state_referenced_locally — initial restore target only
  let visiblePage = $state(page);
  // svelte-ignore state_referenced_locally
  let renderedZoom = $state<number | "auto">(zoom);
  let loadError = $state<string | null>(null);
  let loading = $state(false);
  let searchQuery = $state("");
  let searchOpen = $state(false);
  let searchInputEl: HTMLInputElement | undefined = $state();
  let searchNoMatch = $state(false);
  let currentMatchIdx = $state(-1);
  let totalMatches = $state(0);

  // Slots only carry an immutable index — refs and render bookkeeping live
  // OUTSIDE $state so mutations don't churn the each block.
  let slots = $state<{ index: number }[]>([]);
  const canvases = new Map<number, HTMLCanvasElement>();
  const textLayers = new Map<number, HTMLDivElement>();
  const wrappers = new Map<number, HTMLDivElement>();
  const renderState = new Map<
    number,
    {
      task: { cancel: () => void; promise: Promise<void> } | null;
      textTask: { cancel: () => void } | null;
      scaleAtCss: number | null;
      // Aspect ratio so we can size the placeholder before the canvas is rendered.
      aspect: number | null;
    }
  >();

  let observer: IntersectionObserver | null = null;
  let scrollObserver: IntersectionObserver | null = null;
  let resizeObserver: ResizeObserver | null = null;

  async function load(ck: string | undefined, urlOverride: string | undefined) {
    loadError = null;
    loading = true;
    cancelAllRenders();
    canvases.clear();
    textLayers.clear();
    wrappers.clear();
    renderState.clear();
    if (doc) {
      try {
        await doc.destroy();
      } catch {
        /* ignore */
      }
      doc = null;
    }
    slots = [];
    try {
      let url = urlOverride;
      if (!url) {
        if (!ck) throw new Error("PDFView: neither citekey nor pdfUrl was provided");
        url = await pdfUrlFor(ck);
      }
      const d = await loadPdf(url);
      doc = d;
      totalPages = d.numPages;
      slots = Array.from({ length: d.numPages }, (_, i) => ({ index: i + 1 }));
    } catch (e) {
      loadError = String(e);
    } finally {
      loading = false;
    }
  }

  function cancelAllRenders() {
    for (const st of renderState.values()) {
      if (st.task) {
        try {
          st.task.cancel();
        } catch {
          /* ignore */
        }
        st.task = null;
      }
      if (st.textTask) {
        try {
          st.textTask.cancel();
        } catch {
          /* ignore */
        }
        st.textTask = null;
      }
    }
  }

  function targetCssScale(naturalWidth: number): number {
    if (renderedZoom === "auto" || renderedZoom <= 0) {
      const c = pageList;
      if (!c) return 1.0;
      const usable = Math.max(120, c.clientWidth - 32);
      return Math.max(0.2, usable / naturalWidth);
    }
    return renderedZoom;
  }

  async function ensureRendered(index: number): Promise<void> {
    if (!doc) return;
    const canvas = canvases.get(index);
    if (!canvas) return;
    const page = await doc.getPage(index);
    const naturalViewport = page.getViewport({ scale: 1 });
    const cssScale = targetCssScale(naturalViewport.width);
    let st = renderState.get(index);
    if (!st) {
      st = {
        task: null,
        textTask: null,
        scaleAtCss: null,
        aspect: naturalViewport.width / naturalViewport.height,
      };
      renderState.set(index, st);
    } else if (st.aspect === null) {
      st.aspect = naturalViewport.width / naturalViewport.height;
    }
    // Keep the wrapper sized so layout doesn't pop when the canvas finishes rendering.
    sizeWrapper(index, cssScale, naturalViewport.width, naturalViewport.height);
    if (st.scaleAtCss !== null && Math.abs(st.scaleAtCss - cssScale) < 0.01 && !st.task) {
      return; // already rendered at this scale
    }
    if (st.task) {
      try {
        st.task.cancel();
      } catch {
        /* ignore */
      }
      st.task = null;
    }
    if (st.textTask) {
      try {
        st.textTask.cancel();
      } catch {
        /* ignore */
      }
      st.textTask = null;
    }
    const dpr = window.devicePixelRatio || 1;
    const renderViewport = page.getViewport({ scale: cssScale * dpr });
    const cssViewport = page.getViewport({ scale: cssScale });
    canvas.width = Math.ceil(renderViewport.width);
    canvas.height = Math.ceil(renderViewport.height);
    canvas.style.width = `${renderViewport.width / dpr}px`;
    canvas.style.height = `${renderViewport.height / dpr}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const task = page.render({ canvasContext: ctx, viewport: renderViewport });
    st.task = task;
    try {
      await task.promise;
      st.scaleAtCss = cssScale;
    } catch (e) {
      const msg = String(e);
      // pdfjs throws "RenderingCancelledException" on cancel — expected.
      if (!msg.includes("ancel")) {
        console.warn(`render page ${index} failed`, e);
      }
    } finally {
      if (st.task === task) st.task = null;
    }
    // Render the selectable text layer over the canvas. Cheap relative to the
    // canvas render and adds drag-to-select + ⌘F-target text on the page.
    void renderTextLayer(page, index, cssViewport);
  }

  async function renderTextLayer(
    page: import("pdfjs-dist").PDFPageProxy,
    index: number,
    viewport: import("pdfjs-dist").PageViewport,
  ): Promise<void> {
    const container = textLayers.get(index);
    if (!container) return;
    container.replaceChildren();
    container.style.width = `${viewport.width}px`;
    container.style.height = `${viewport.height}px`;
    container.style.setProperty("--scale-factor", String(viewport.scale));
    try {
      const layer = new TextLayer({
        textContentSource: page.streamTextContent(),
        container,
        viewport,
      });
      await layer.render();
      // If a query is active, highlight matches in this freshly rendered layer.
      if (searchQuery.trim()) {
        highlightInLayer(container, searchQuery);
        refreshMatchCounts();
      }
    } catch (e) {
      const msg = String(e);
      if (!msg.includes("ancel")) {
        console.warn(`text layer render page ${index} failed`, e);
      }
    }
  }

  function sizeWrapper(index: number, cssScale: number, natW: number, natH: number) {
    const wrap = wrappers.get(index);
    if (!wrap) return;
    wrap.style.width = `${Math.round(natW * cssScale)}px`;
    wrap.style.height = `${Math.round(natH * cssScale)}px`;
  }

  function isInViewport(el: HTMLElement): boolean {
    const root = pageList;
    if (!root) return false;
    const r = el.getBoundingClientRect();
    const rr = root.getBoundingClientRect();
    return r.bottom >= rr.top - rr.height && r.top <= rr.bottom + rr.height;
  }

  function setupObservers() {
    if (!pageList) return;
    observer?.disconnect();
    scrollObserver?.disconnect();
    resizeObserver?.disconnect();
    observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const idx = Number((e.target as HTMLElement).dataset.idx);
          if (Number.isFinite(idx)) void ensureRendered(idx);
        }
      },
      { root: pageList, rootMargin: "200px 0px" },
    );
    scrollObserver = new IntersectionObserver(
      (entries) => {
        let best: { idx: number; ratio: number } | null = null;
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const idx = Number((e.target as HTMLElement).dataset.idx);
          if (!best || e.intersectionRatio > best.ratio) best = { idx, ratio: e.intersectionRatio };
        }
        if (best) {
          visiblePage = best.idx;
          if (tabsState.tabs[tabsState.activeIndex]?.citekey === citekey) {
            updateActiveTabPdf({ pdfPage: best.idx });
          }
        }
      },
      { root: pageList, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    // Fit-width must reflow when the pages container resizes (pane drag, window resize, etc).
    resizeObserver = new ResizeObserver(() => {
      if (renderedZoom !== "auto") return;
      reflowVisible();
    });
    resizeObserver.observe(pageList);
  }

  let reflowTimer: number | null = null;
  function reflowVisible() {
    if (reflowTimer !== null) window.clearTimeout(reflowTimer);
    reflowTimer = window.setTimeout(() => {
      reflowTimer = null;
      for (const [idx, wrap] of wrappers) {
        if (isInViewport(wrap)) void ensureRendered(idx);
      }
    }, 80);
  }

  function attachWrapper(node: HTMLDivElement, idx: number) {
    wrappers.set(idx, node);
    observer?.observe(node);
    scrollObserver?.observe(node);
    return {
      destroy() {
        wrappers.delete(idx);
        observer?.unobserve(node);
        scrollObserver?.unobserve(node);
      },
    };
  }

  function attachCanvas(node: HTMLCanvasElement, idx: number) {
    canvases.set(idx, node);
    // If we already know the wrapper is in the viewport, render immediately.
    const wrap = wrappers.get(idx);
    if (wrap && isInViewport(wrap)) void ensureRendered(idx);
    return {
      destroy() {
        if (canvases.get(idx) === node) canvases.delete(idx);
      },
    };
  }

  function attachTextLayer(node: HTMLDivElement, idx: number) {
    textLayers.set(idx, node);
    return {
      destroy() {
        if (textLayers.get(idx) === node) textLayers.delete(idx);
      },
    };
  }

  function gotoPage(p: number) {
    p = Math.max(1, Math.min(totalPages, p));
    const wrap = wrappers.get(p);
    wrap?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setZoom(z: number | "auto") {
    if (z === renderedZoom) return;
    renderedZoom = z;
    // Invalidate every cached scale so re-renders happen at the new zoom.
    for (const st of renderState.values()) st.scaleAtCss = null;
    if (tabsState.tabs[tabsState.activeIndex]?.citekey === citekey) {
      updateActiveTabPdf({ pdfZoom: z });
    }
    // Re-render any currently-visible pages immediately; the rest happen on intersection.
    for (const [idx, wrap] of wrappers) {
      if (isInViewport(wrap)) void ensureRendered(idx);
    }
  }

  function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Wrap occurrences of `query` in this text layer's spans with
   *  <mark class="pdf-find-match"> so they pick up our yellow highlight CSS. */
  function highlightInLayer(layer: HTMLDivElement, query: string): void {
    // First clear any existing marks by collapsing each span's children into
    // its plain textContent.
    for (const span of Array.from(layer.querySelectorAll<HTMLElement>("span"))) {
      if (span.querySelector("mark.pdf-find-match")) {
        span.textContent = span.textContent;
      }
    }
    if (!query.trim()) return;
    const re = new RegExp(escapeRegExp(query), "gi");
    for (const span of Array.from(layer.querySelectorAll<HTMLElement>("span"))) {
      // Skip non-leaf spans (pdfjs sometimes nests for marked content); we'll
      // hit the leaves on the next iteration.
      if (span.childElementCount > 0) continue;
      const text = span.textContent ?? "";
      if (!re.test(text)) continue;
      re.lastIndex = 0;
      const html = escapeHtml(text).replace(re, (m) =>
        `<mark class="pdf-find-match">${escapeHtml(m)}</mark>`,
      );
      span.innerHTML = html;
    }
  }

  function listAllMatches(): HTMLElement[] {
    if (!pageList) return [];
    return Array.from(pageList.querySelectorAll<HTMLElement>("mark.pdf-find-match"));
  }

  function refreshMatchCounts(): void {
    const matches = listAllMatches();
    totalMatches = matches.length;
    if (matches.length === 0) {
      currentMatchIdx = -1;
      return;
    }
    if (currentMatchIdx >= matches.length) currentMatchIdx = -1;
  }

  /** Re-apply highlights across every rendered text layer. Called when the
   *  query changes (debounced) and after each new text layer renders. */
  function highlightAllRendered(): void {
    for (const [, layer] of textLayers) {
      highlightInLayer(layer, searchQuery);
    }
    refreshMatchCounts();
  }

  // Debounced effect: re-highlight when the query changes.
  let highlightTimer: number | null = null;
  $effect(() => {
    void searchQuery;
    if (highlightTimer !== null) window.clearTimeout(highlightTimer);
    highlightTimer = window.setTimeout(() => {
      currentMatchIdx = -1;
      highlightAllRendered();
      // If query non-empty, jump to the first match for quick feedback.
      if (searchQuery.trim() && totalMatches > 0) gotoMatch("forward");
      searchNoMatch = !!searchQuery.trim() && totalMatches === 0;
    }, 150);
  });

  /** Navigate the next/previous highlighted match. Adds .current class to
   *  the active mark and scrolls it into view. */
  function gotoMatch(direction: "forward" | "backward"): void {
    if (!searchQuery.trim()) return;
    const matches = listAllMatches();
    if (matches.length === 0) {
      searchNoMatch = true;
      totalMatches = 0;
      currentMatchIdx = -1;
      return;
    }
    searchNoMatch = false;
    totalMatches = matches.length;
    let next = currentMatchIdx;
    if (next < 0) {
      next = direction === "forward" ? 0 : matches.length - 1;
    } else {
      next += direction === "forward" ? 1 : -1;
      if (next < 0) next = matches.length - 1;
      if (next >= matches.length) next = 0;
    }
    // Clear .current from EVERY mark (not just the last index we tracked) —
    // newly-rendered text layers can introduce marks that don't get wiped
    // by an index-based clear, and the resulting "stuck" highlight makes it
    // hard to tell which match the user is actually on.
    if (pageList) {
      for (const m of pageList.querySelectorAll<HTMLElement>("mark.pdf-find-match.current")) {
        m.classList.remove("current");
      }
    }
    matches[next].classList.add("current");
    scrollMatchIntoViewIfNeeded(matches[next]);
    currentMatchIdx = next;
  }

  /** Minimal-scroll behaviour: if the match is already fully on screen, do
   *  nothing. Otherwise scroll just enough to bring it onto the visible edge —
   *  top-aligned if it's above, bottom-aligned if it's below. The 24px
   *  scroll-margin-* declared on the mark element keeps it from sitting flush
   *  against the toolbar / edge. */
  function scrollMatchIntoViewIfNeeded(el: HTMLElement): void {
    if (!pageList) return;
    const root = pageList.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (r.top >= root.top && r.bottom <= root.bottom) return; // already visible
    if (r.top < root.top) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      el.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }

  function findNext(direction: "forward" | "backward" = "forward"): void {
    gotoMatch(direction);
  }

  /** Open the find panel and focus the input — fired by the global ⌘⇧F
   *  handler via `tabsState.pdfFindFocusToken`. Only the active tab's
   *  PDFView responds (inactive tabs are display:none anyway). */
  $effect(() => {
    void tabsState.pdfFindFocusToken;
    untrack(() => {
      if (tabsState.tabs[tabsState.activeIndex]?.citekey !== citekey) return;
      searchOpen = true;
      setTimeout(() => searchInputEl?.select(), 0);
    });
  });

  onMount(async () => {
    setupObservers();
    await load(citekey, pdfUrl);
    setTimeout(() => {
      if (page > 1) gotoPage(page);
    }, 80);
  });

  // Re-load when either the tab's citekey OR the direct URL changes.
  // svelte-ignore state_referenced_locally
  let lastCitekey = $state(citekey);
  // svelte-ignore state_referenced_locally
  let lastPdfUrl = $state(pdfUrl);
  $effect(() => {
    if (citekey !== lastCitekey || pdfUrl !== lastPdfUrl) {
      lastCitekey = citekey;
      lastPdfUrl = pdfUrl;
      void load(citekey, pdfUrl);
    }
  });

  onDestroy(() => {
    cancelAllRenders();
    observer?.disconnect();
    scrollObserver?.disconnect();
    resizeObserver?.disconnect();
    if (doc) {
      void doc.destroy();
      doc = null;
    }
  });
</script>

<div class="pdfview">
  <div class="toolbar">
    <button class="nav" title="Previous page (←)" onclick={() => gotoPage(visiblePage - 1)} disabled={!doc}>‹ <span class="caps-inline">Prev</span></button>
    <span class="page">
      <input
        type="number"
        min="1"
        max={totalPages || 1}
        value={visiblePage}
        onchange={(e) => gotoPage(Number((e.target as HTMLInputElement).value))}
        disabled={!doc}
      /> <span class="slash">/</span> {totalPages || "–"}
    </span>
    <button class="nav" title="Next page (→)" onclick={() => gotoPage(visiblePage + 1)} disabled={!doc}><span class="caps-inline">Next</span> ›</button>
    <span class="sep"></span>
    <button class="zoom" title="Fit width" class:active={renderedZoom === "auto"} onclick={() => setZoom("auto")}>Fit</button>
    <button class="zoom" title="Zoom out" onclick={() => setZoom(typeof renderedZoom === "number" ? Math.max(0.25, renderedZoom - 0.1) : 0.9)} disabled={!doc}>−</button>
    <button class="zoom" title="Zoom in" onclick={() => setZoom(typeof renderedZoom === "number" ? Math.min(4, renderedZoom + 0.1) : 1.1)} disabled={!doc}>+</button>
    <span class="zoom-label">{typeof renderedZoom === "number" ? Math.round(renderedZoom * 100) + "%" : ""}</span>
    <span class="spacer"></span>
    <button class="zoom" title="Find in PDF" class:active={searchOpen} onclick={() => (searchOpen = !searchOpen)}>Find <kbd>⌘⇧F</kbd></button>
  </div>
  {#if searchOpen}
    <div class="search">
      <input
        type="search"
        placeholder="Find in PDF…"
        bind:this={searchInputEl}
        bind:value={searchQuery}
        onkeydown={(e) => {
          if (e.key === "Enter") findNext(e.shiftKey ? "backward" : "forward");
          else if (e.key === "Escape") {
            e.preventDefault();
            searchOpen = false;
            searchQuery = "";
            searchNoMatch = false;
          }
        }}
      />
      <span class="match-count" class:dim={!searchQuery.trim()}>
        {#if searchQuery.trim() && totalMatches > 0}
          <span class="current">{currentMatchIdx + 1}</span>
          <span class="of">/</span>
          <span>{totalMatches}</span>
        {:else if searchQuery.trim()}
          <span class="no-match">no matches</span>
        {:else}
          &nbsp;
        {/if}
      </span>
      <button onclick={() => findNext("backward")} title="Previous match" disabled={totalMatches === 0}>‹</button>
      <button onclick={() => findNext("forward")} title="Next match" disabled={totalMatches === 0}>›</button>
    </div>
  {/if}
  {#if loadError}
    <div class="banner err">PDF unavailable: {loadError}</div>
  {/if}
  {#if loading && !loadError}
    <div class="banner muted">Loading PDF…</div>
  {/if}
  <div class="pages" bind:this={pageList}>
    {#each slots as slot (slot.index)}
      <div class="page-slot" data-idx={slot.index} use:attachWrapper={slot.index}>
        <canvas use:attachCanvas={slot.index}></canvas>
        <div class="textLayer" use:attachTextLayer={slot.index}></div>
      </div>
    {/each}
  </div>
</div>

<style>
  .pdfview {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--backdrop);
  }
  /* PDF toolbar — direction-b.jsx: height 30, padding 0 18px, gap 14,
     border-bottom 1px ink12, Inter 10px ink70 letter-spacing 0.5
     uppercase. Page count "1 / 17" is JetBrainsMono 10px ink, no caps,
     letter-spacing 0. "Fit" is accent 700, inactive zoom buttons are
     ink50. "find ⌘F" right-aligned ink50. */
  .toolbar {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 18px;
    height: 30px;
    border-bottom: 1px solid var(--ink-12);
    flex-shrink: 0;
    font-family: var(--sans);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    color: var(--ink-70);
    background: var(--backdrop);
  }
  .toolbar button {
    padding: 0;
    font: inherit;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    border: 0;
    background: transparent;
    color: var(--ink-50);
    cursor: pointer;
    border-radius: 0;
  }
  .toolbar button:hover:not(:disabled) {
    color: var(--ink);
  }
  .toolbar button.active {
    color: var(--accent);
    font-weight: 700;
  }
  .toolbar button.zoom {
    min-width: 14px;
  }
  .toolbar .nav {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .toolbar .sep {
    width: 1px;
    height: 12px;
    background: var(--divider);
  }
  .toolbar .spacer {
    flex: 1;
  }
  .toolbar .page {
    display: inline-flex;
    gap: 4px;
    align-items: baseline;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink);
    text-transform: none;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
    font-weight: 400;
  }
  .toolbar .page .slash {
    color: var(--ink-30);
  }
  .toolbar input[type="number"] {
    width: 22px;
    border: 0;
    background: transparent;
    padding: 0;
    text-align: center;
    font: inherit;
    font-family: var(--mono);
    color: var(--ink);
    -moz-appearance: textfield;
    appearance: textfield;
  }
  .toolbar input[type="number"]::-webkit-inner-spin-button,
  .toolbar input[type="number"]::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  .toolbar .caps-inline {
    display: inline-block;
  }
  .zoom-label {
    color: var(--ink-30);
    min-width: 0;
    text-align: left;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    font-size: 9px;
  }
  .toolbar kbd {
    font-family: var(--mono);
    font-size: 9px;
    color: var(--ink-50);
    margin-left: 2px;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
  }
  .search {
    display: flex;
    gap: 6px;
    padding: 6px 18px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--surface-soft);
    align-items: center;
  }
  .search input {
    flex: 1;
    border: 1px solid var(--ink-12);
    background: var(--panel);
    padding: 3px 8px;
    font-size: 12px;
    font-family: var(--serif);
  }
  .search input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .search button {
    border: 1px solid var(--ink-12);
    background: var(--panel);
    padding: 2px 8px;
    font-size: 12px;
    line-height: 1;
    color: var(--ink);
    cursor: pointer;
  }
  .search button:hover {
    background: var(--hover);
  }
  .no-match {
    font-family: var(--sans);
    font-size: 10px;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
  }
  .match-count {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-70);
    font-variant-numeric: tabular-nums;
    min-width: 56px;
    text-align: center;
    flex-shrink: 0;
  }
  .match-count .current {
    color: var(--ink);
    font-weight: 700;
  }
  .match-count .of {
    color: var(--ink-30);
    margin: 0 2px;
  }
  .match-count.dim {
    color: var(--ink-30);
  }
  .pages {
    flex: 1 1 auto;
    overflow-y: auto;
    background: var(--backdrop);
    padding: 32px 44px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    align-items: center;
    contain: strict;
  }
  .page-slot {
    position: relative;
    background: #ffffff;
    box-shadow: 0 1px 1px rgba(0, 0, 0, 0.04), 0 12px 36px rgba(26, 22, 18, 0.12);
    border: 0.5px solid var(--ink-12);
    /* Concrete dimensions get set by JS once the page has been measured;
       this fallback keeps the block from collapsing before that. */
    width: 600px;
    min-height: 200px;
    flex: 0 0 auto;
    display: block;
  }

  /* PDF text layer — invisible spans positioned over the canvas so the user
     can click-and-drag select text (and ⌘F can locate hits). Layout / sizing
     ported from pdfjs-dist's web/pdf_viewer.css. */
  .textLayer {
    position: absolute;
    text-align: initial;
    inset: 0;
    overflow: clip;
    opacity: 1;
    line-height: 1;
    -webkit-text-size-adjust: none;
    text-size-adjust: none;
    forced-color-adjust: none;
    transform-origin: 0 0;
    caret-color: CanvasText;
    z-index: 0;
    user-select: text;
  }
  .textLayer :global(span),
  .textLayer :global(br) {
    color: transparent;
    position: absolute;
    white-space: pre;
    cursor: text;
    transform-origin: 0% 0%;
  }
  .textLayer :global(::selection) {
    background: rgba(122, 58, 20, 0.28);
  }
  .textLayer :global(.highlight) {
    background: rgba(244, 191, 80, 0.45);
    margin: -1px;
    padding: 1px;
    border-radius: 2px;
  }
  .textLayer :global(.highlight.selected) {
    background: rgba(244, 191, 80, 0.85);
  }
  /* Find highlights — soft yellow tint over the rasterized page. */
  .textLayer :global(mark.pdf-find-match) {
    background: rgba(244, 191, 80, 0.35);
    color: transparent;
    padding: 0;
    margin: 0;
    border-radius: 1px;
    /* Used by scrollIntoView({block:'start'|'end'}) so the match never sits
       flush against the toolbar or page edge after a scroll. */
    scroll-margin: 24px 0;
  }
  /* Current match — much louder so it's unambiguous which one is the
     navigation cursor. Bright orange-amber + thick rust outline. */
  .textLayer :global(mark.pdf-find-match.current) {
    background: rgba(244, 140, 30, 0.9);
    box-shadow: 0 0 0 2px var(--accent), 0 0 0 4px rgba(122, 58, 20, 0.25);
  }
  .textLayer :global(.endOfContent) {
    display: block;
    position: absolute;
    inset: 100% 0 0 0;
    z-index: -1;
    cursor: default;
    user-select: none;
  }
  .page-slot canvas {
    display: block;
    /* Width/height are set imperatively (intrinsic + style px). */
  }
  .banner {
    padding: 6px 12px;
    font-size: 12px;
    border-bottom: 1px solid var(--border);
  }
  .banner.err {
    background: #ffe9e6;
    color: #6c1e0e;
  }
  @media (prefers-color-scheme: dark) {
    .banner.err {
      background: #3a1813;
      color: #ffb1a3;
    }
  }
  .banner.muted {
    color: var(--muted);
  }
</style>

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
  import { useViewportCapability } from "@embedpdf/plugin-viewport/svelte";
  import { PdfAnnotationSubtype, PdfBlendMode } from "@embedpdf/models";
  import { tabsState } from "../state/tabs.svelte";
  import { HIGHLIGHT_COLORS } from "../lib/highlight-colors";
  import { prefsState, toggleFocusMode } from "../state/prefs.svelte";
  import {
    pdfNavState,
    consumeBookmarkMove,
    setDocumentTotalPages,
  } from "../state/pdfNav.svelte";

  type Props = { documentId: string; citekey: string };
  let { documentId, citekey }: Props = $props();

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
  const viewportCap = useViewportCapability();

  /* Publish totalPages so the right pane's bookmark row can show
   * "p.X/N" without needing its own EmbedPDF instance. The scroll
   * plugin's `totalPages` is 0/undefined until the document finishes
   * loading; only write once it's a positive number. */
  $effect(() => {
    const n = scroll.state.totalPages ?? 0;
    if (n > 0) setDocumentTotalPages(citekey, n);
  });

  /* Listen for "move bookmark here" from the right-pane bookmark bar.
   * The bar can't call setOrMoveBookmark directly because it lives
   * outside the EmbedPDF plugin tree. We compare the request's citekey
   * to ours so only the toolbar of the matching tab acts on it.
   * 2-second staleness guard prevents a freshly-mounted toolbar from
   * consuming an old request and jumping the bookmark to page 1. */
  $effect(() => {
    const req = pdfNavState.pendingBookmarkMove;
    if (!req || req.citekey !== citekey) return;
    if (Date.now() - req.ts > 2000) {
      consumeBookmarkMove();
      return;
    }
    untrack(() => {
      setOrMoveBookmark();
      consumeBookmarkMove();
    });
  });

  /* The annotation bar is a separate, toggleable popout — keeps the
   * main reading toolbar uncluttered. In normal mode it slides out
   * below the toolbar; in focus mode the main toolbar is a vertical
   * strip on the left, and the annotate popout becomes a second
   * vertical strip immediately to its right (same writing-mode, so
   * the tool icons stack the same way). Two tools live in it:
   *
   *   - STICKY NOTE  → EmbedPDF's `textComment` tool. Drops a small
   *     yellow icon; click-through opens a comment editor.
   *   - TEXT BOX     → EmbedPDF's `freeText` tool. Drops a yellow
   *     post-it whose contents are always visible and auto-grow.
   *
   * Both auto-deactivate after a single drop (create-event listener
   * below). */
  let annotateOpen = $state(false);
  type ToolId =
    | "textComment"   // sticky note
    | "freeText"      // post-it text box
    | "square"        // rectangle
    | "circle"        // ellipse
    | "line"          // arrow (line with arrow end-style)
    | "ink";          // free-draw pencil
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

  /* Auto-deactivate the tool after the user drops a single annotation,
   * so the next click on the just-placed note moves/edits it rather
   * than dropping a second one. Skip the deactivate when the just-
   * created TEXT is a bookmark (the bookmark button uses its own
   * create path and doesn't engage a click-to-place tool). */
  $effect(() => {
    const provides = annotation.provides;
    if (!provides) return;
    const off = provides.onAnnotationEvent((evt) => {
      if (evt.type !== "create") return;
      const ann = evt.annotation as
        | { id?: string; type?: number; custom?: { bookmark?: boolean }; pageIndex?: number }
        | undefined;
      if (!ann) return;
      const current = untrack(() => activeToolId);
      /* FreeText post-create color patch — turn the bundled red-on-
       * transparent default into a yellow post-it. Runs independently
       * of the auto-deactivate below. */
      if (
        ann.type === PdfAnnotationSubtype.FREETEXT &&
        typeof ann.id === "string" &&
        typeof ann.pageIndex === "number"
      ) {
        provides.updateAnnotation(ann.pageIndex, ann.id, {
          color: "#FFF59D",
          backgroundColor: "#FFF59D",
          fontColor: "#1A1612",
          opacity: 0.95,
        } as Parameters<typeof provides.updateAnnotation>[2]);
      }
      /* Auto-deactivate after creation for every click-to-place tool
       * so the next click on the just-placed annotation lets the user
       * edit / move it instead of dropping a second one. */
      const matches =
        (current === "textComment" && ann.type === PdfAnnotationSubtype.TEXT && !ann.custom?.bookmark) ||
        (current === "freeText" && ann.type === PdfAnnotationSubtype.FREETEXT) ||
        (current === "square" && ann.type === PdfAnnotationSubtype.SQUARE) ||
        (current === "circle" && ann.type === PdfAnnotationSubtype.CIRCLE) ||
        (current === "line" && ann.type === PdfAnnotationSubtype.LINE) ||
        (current === "ink" && ann.type === PdfAnnotationSubtype.INK);
      if (matches) {
        activeToolId = null;
        provides.setActiveTool(null);
      }
      /* Suppress the auto-popup of the comment menu on creation: the
       * plugin selects fresh annotations by default, which pops the
       * comment textarea immediately. The user wants the menu only on
       * an explicit click. Skip bookmarks (their menu only has a
       * single "remove" action so no harm letting it stay selected,
       * and the toolbar's bookmark button doesn't want a flash of
       * menu either way — deselecting is fine here too). FreeText
       * stays selected because the user just placed it and the visual
       * selection handles are needed to resize / move it before they
       * commit. */
      if (ann.type !== PdfAnnotationSubtype.FREETEXT && typeof ann.id === "string") {
        provides.deselectAnnotation();
      }
    });
    return () => off?.();
  });

  /* ---- Bookmark ---------------------------------------------------------
   * One bookmark per paper, stored as a TEXT annotation with
   * `custom.bookmark = true`. Toolbar button creates or moves it to the
   * current viewport's centre. Jumping back happens via the right-pane
   * Annotations tab (single-click on the bookmark row), reusing the
   * existing requestJump pipeline.
   */
  type BookmarkAnno = { id: string; pageIndex: number; rect?: { origin: { x: number; y: number }; size: { width: number; height: number } } };
  /* Reactive lookup of the current bookmark — re-evaluates whenever the
   * annotation plugin's `selectedUids`/`byUid` proxies tick. `state.byUid`
   * is the canonical map; pageVisibilityMetrics changes don't matter
   * here. */
  const bookmark = $derived.by<BookmarkAnno | null>(() => {
    void annotation.state.selectedUids; // touch state to track reactivity
    const provides = annotation.provides;
    if (!provides) return null;
    const all = provides.getAnnotations();
    for (const t of all) {
      const o = t.object as { id: string; pageIndex: number; custom?: { bookmark?: boolean }; rect?: BookmarkAnno["rect"] };
      if (o.custom?.bookmark === true) {
        return { id: o.id, pageIndex: o.pageIndex, rect: o.rect };
      }
    }
    return null;
  });

  const BOOKMARK_SIZE = 24;

  function setOrMoveBookmark() {
    const provides = annotation.provides;
    const sp = scroll.provides;
    if (!provides || !sp) return;
    /* Pick the most-visible page and the page-coord midpoint of its
     * visible window — that's "where I'm currently reading".
     *
     * Fallback: `pageVisibilityMetrics` is populated lazily by the
     * scroll plugin (IntersectionObserver-driven). On a fresh PDF
     * load where the user hasn't scrolled yet, the metrics array can
     * be empty, which used to make this function silently no-op.
     * That's the "click set here and nothing happens" symptom. We
     * now fall back to `scroll.state.currentPage` (which is reliable
     * after the doc loads) and place the bookmark rect at the page
     * origin — the bookmark is invisible on the PDF page anyway
     * (it lives only in the right-pane bar), so the rect's exact
     * position doesn't matter, only its `pageIndex`. */
    const metrics = sp.getMetrics();
    const stateCurrent = scroll.state.currentPage ?? 1;
    const rawCurrent = metrics?.currentPage ?? stateCurrent;
    // Defensive clamp: pages are 1-based in the plugin's API. A
    // stray 0 (e.g. mid-init state) would make pageIndex = -1 and
    // the createAnnotation call would fail silently.
    const current = Math.max(1, rawCurrent | 0);
    const pageVis = metrics?.pageVisibilityMetrics?.find((m) => m.pageNumber === current);
    let cx: number;
    let cy: number;
    if (pageVis) {
      cx = pageVis.original.pageX + pageVis.original.visibleWidth / 2;
      cy = pageVis.original.pageY + pageVis.original.visibleHeight / 2;
    } else {
      /* No visibility metrics yet — anchor at top-left of the page
       * (page coords are top-origin in this plugin). The bookmark
       * has no visual on the page so this is just bookkeeping. */
      cx = BOOKMARK_SIZE / 2;
      cy = BOOKMARK_SIZE / 2;
    }
    const rect = {
      origin: { x: cx - BOOKMARK_SIZE / 2, y: cy - BOOKMARK_SIZE / 2 },
      size: { width: BOOKMARK_SIZE, height: BOOKMARK_SIZE },
    };
    /* Always delete-then-create. updateAnnotation's reducer patches the
     * annotation's fields but keeps it indexed under its original page
     * in `state.pages`, so a same-page rect change works but a cross-
     * page move leaves a phantom on the old page and nothing on the
     * new one. createAnnotation correctly inserts under the new page,
     * so we just remove and re-insert. */
    const existing = bookmark;
    if (existing) {
      provides.deleteAnnotation(existing.pageIndex, existing.id);
    }
    const newId = crypto.randomUUID();
    provides.createAnnotation(current - 1, {
      id: newId,
      pageIndex: current - 1,
      type: PdfAnnotationSubtype.TEXT,
      rect,
      strokeColor: "#7a3a14", // accent
      color: "#7a3a14",
      opacity: 1,
      blendMode: PdfBlendMode.Normal,
      author: "Literature Vault",
      created: new Date(),
      flags: ["print", "noRotate", "noZoom"],
      contents: "",
      custom: { bookmark: true },
    } as Parameters<typeof provides.createAnnotation>[1]);
  }

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

  /* FIT = fit-to-height: zoom so the tallest page exactly fills the
   * viewport's vertical content area. One page top + bottom anchored
   * to the viewport, no margin. The horizontal recess depends on how
   * the column's width compares to the page's natural aspect. */
  function fit() {
    const sp = scroll.provides;
    const vpProv = viewportCap.provides;
    if (!sp || !vpProv) return;
    const spreads = sp.getSpreadPagesWithRotatedSize();
    if (!spreads || spreads.length === 0) return;
    let pageH = 0;
    for (const spread of spreads) {
      for (const page of spread) {
        if (page.rotatedSize.height > pageH) pageH = page.rotatedSize.height;
      }
    }
    if (pageH <= 0) return;
    const vpMetrics = vpProv.forDocument(documentId).getMetrics();
    const clientHeight = vpMetrics?.clientHeight ?? 0;
    if (clientHeight <= 0) return;
    /* Use the full clientHeight so page height === viewport height
     * exactly. Earlier subtracting 2 * viewportGap left 10px bands top
     * and bottom — user wants no margin. The plugin's own viewportGap
     * still produces a separator between pages on scroll, but the
     * single-page fit no longer carves out a permanent band. */
    zoom.provides?.requestZoom(clientHeight / pageH);
    /* Snap to the top of the current page so the user starts reading
     * from the page top rather than wherever the focal-point
     * preservation dropped them after the zoom. Wait two frames so the
     * zoom-driven layout has actually committed before scrolling — a
     * microtask runs too early and the scrollToPage computes against
     * the previous scale, leaving the page mid-viewport. */
    const currentPage = sp.getMetrics()?.currentPage ?? 1;
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        sp.scrollToPage({ pageNumber: currentPage, alignY: 0, behavior: "auto" }),
      ),
    );
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

  /* When the active match index changes, ensure the match is in view.
   *
   * Strategy: skip the scroll if the match's rect is already inside the
   * visible portion of its page (so consecutive matches in view don't
   * jitter the viewport); otherwise, smoothly scroll to centre the
   * match by passing its midpoint as `pageCoordinates` with
   * alignX/Y = 50.
   *
   * The old "current-page → no scroll" shortcut was wrong when a page
   * was taller than the viewport — matches on the lower half of the
   * current page were left off-screen with no scroll fired. The new
   * visibility check uses pageVisibilityMetrics.original (page-coord
   * window) directly, so it works regardless of zoom or page count. */
  $effect(() => {
    const idx = search.state.activeResultIndex ?? -1;
    const results = search.state.results;
    if (idx < 0 || !results || !results[idx]) return;
    const result = results[idx];
    const targetPage = (result.pageIndex ?? 0) + 1;
    const firstRect = result.rects?.[0];
    if (!firstRect) return;

    const sp = scroll.provides;
    if (!sp) return;

    /* If the match is already comfortably on-screen, don't move the
     * viewport. "Comfortably" means inside the *central* 60% of the
     * visible y-window — a match peeking at the very top or bottom
     * edge of the viewport (e.g. when only a thin sliver of page N+1
     * is visible) still triggers a centring scroll, so the user
     * doesn't have to hunt for it. */
    const COMFORT_PAD = 0.2; // skip the top/bottom 20% of the visible window
    const metrics = untrack(() => sp.getMetrics());
    const pageVis = metrics?.pageVisibilityMetrics?.find(
      (m) => m.pageNumber === targetPage,
    );
    if (pageVis) {
      const matchTop = firstRect.origin.y;
      const matchBottom = matchTop + (firstRect.size?.height ?? 0);
      const visTop = pageVis.original.pageY;
      const visHeight = pageVis.original.visibleHeight;
      const comfortTop = visTop + visHeight * COMFORT_PAD;
      const comfortBottom = visTop + visHeight * (1 - COMFORT_PAD);
      if (matchTop >= comfortTop && matchBottom <= comfortBottom) return;
    }

    sp.scrollToPage({
      pageNumber: targetPage,
      pageCoordinates: {
        x: firstRect.origin.x + (firstRect.size?.width ?? 0) / 2,
        y: firstRect.origin.y + (firstRect.size?.height ?? 0) / 2,
      },
      alignX: 50,
      alignY: 50,
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
    /* Escape priority: deactivate an active annotation tool first, then
     * close the find bar, then defer to App's keymap (which exits focus
     * mode). preventDefault + return early after each handled case so
     * one press isn't multi-consumed. */
    if (e.key === "Escape" && activeToolId !== null && !isTextInput(e.target)) {
      e.preventDefault();
      e.stopPropagation();
      toggleTool(null);
      return;
    }
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

<div class="ep-toolbar-wrap" class:focus={prefsState.focusMode}>
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
      <!-- BOOKMARK button intentionally lives only in the right-pane
           bookmark bar (between frontmatter and the EDIT/PREVIEW/
           ANNOTATIONS toggle). The bar's "set here" / "move here"
           actions dispatch requestBookmarkMove which we still listen
           to via pdfNavState.pendingBookmarkMove. -->
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
      <button
        class="btn focus-toggle"
        class:active={prefsState.focusMode}
        onclick={() => void toggleFocusMode()}
        title={prefsState.focusMode ? "Exit focus mode (Esc)" : "Focus mode — fullscreen, hide everything except PDF + notes (⌘⇧F)"}
      >
        {prefsState.focusMode ? "EXIT FOCUS" : "FOCUS"}
      </button>
    </div>
  </div>

  <!-- Annotation popout. Slides below the toolbar in normal mode; in
       focus mode it inherits the sideways writing-mode and sits to the
       right of the vertical strip as a second column. -->
  {#if annotateOpen}
    <div class="annotate-row">
      <!-- Group 1: text annotations -->
      <button
        type="button"
        class="btn tool tool-freetext"
        class:active={activeToolId === "freeText"}
        onclick={() => toggleTool("freeText")}
        aria-pressed={activeToolId === "freeText"}
        aria-label="Text box"
        title="Drop an inline text box (visible on the page)"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <rect x="2" y="2" width="16" height="16" rx="1" fill="none" stroke="currentColor" stroke-width="1.2" />
          <text x="10" y="14.5" text-anchor="middle" font-family="Georgia, serif" font-weight="700" font-size="11" fill="currentColor">T</text>
        </svg>
      </button>
      <button
        type="button"
        class="btn tool tool-sticky"
        class:active={activeToolId === "textComment"}
        onclick={() => toggleTool("textComment")}
        aria-pressed={activeToolId === "textComment"}
        aria-label="Sticky note"
        title="Drop a sticky-note icon (click to read the comment)"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <path
            d="M 0.5 15.5 L 0.5 0.5 L 19.5 0.5 L 19.5 15.5 L 8.5 15.5 L 6.5 19.5 L 4.5 15.5 Z"
            fill="#FFCD45"
            stroke="currentColor"
            stroke-width="1"
            stroke-linejoin="miter"
          />
        </svg>
      </button>

      <span class="tool-sep"></span>

      <!-- Group 2: shapes -->
      <button
        type="button"
        class="btn tool"
        class:active={activeToolId === "square"}
        onclick={() => toggleTool("square")}
        aria-pressed={activeToolId === "square"}
        aria-label="Rectangle"
        title="Draw a rectangle"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <rect x="2" y="3.5" width="16" height="13" rx="0.5" fill="none" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
      <button
        type="button"
        class="btn tool"
        class:active={activeToolId === "circle"}
        onclick={() => toggleTool("circle")}
        aria-pressed={activeToolId === "circle"}
        aria-label="Ellipse"
        title="Draw an ellipse"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <ellipse cx="10" cy="10" rx="8" ry="6.5" fill="none" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
      <button
        type="button"
        class="btn tool"
        class:active={activeToolId === "line"}
        onclick={() => toggleTool("line")}
        aria-pressed={activeToolId === "line"}
        aria-label="Arrow"
        title="Draw an arrow"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M 3 16 L 16 4 M 16 4 L 11 4.5 M 16 4 L 15.5 9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      <span class="tool-sep"></span>

      <!-- Group 3: free-hand draw -->
      <button
        type="button"
        class="btn tool"
        class:active={activeToolId === "ink"}
        onclick={() => toggleTool("ink")}
        aria-pressed={activeToolId === "ink"}
        aria-label="Pencil"
        title="Free-draw with the pen"
      >
        <svg class="tool-svg" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M 14.5 3 L 17 5.5 L 6.5 16 L 3 17 L 4 13.5 Z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
          <line x1="13" y1="4.5" x2="15.5" y2="7" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>

      <span class="tool-sep"></span>

      <!-- Group 4: highlight colour (popover not yet implemented) -->
      <button
        type="button"
        class="btn tool tool-color"
        disabled
        aria-label="Highlight colour"
        title="Highlight colour — coming soon. Select text to highlight."
      >
        <span class="color-dot" style:background={HIGHLIGHT_COLORS[0]} aria-hidden="true"></span>
        <span class="color-caret" aria-hidden="true">▾</span>
      </button>

      <span class="grow"></span>
      <span class="annotate-hint">Select text to highlight.</span>
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

  /* ---- Focus mode layout (rotated-sideways toolbar) -------------------
   * In focus mode the same horizontal toolbar markup is rendered with
   * `writing-mode: vertical-rl`, which rotates each child glyph and
   * the layout's main axis 90° clockwise: what was a left-to-right row
   * becomes a top-to-bottom column with labels reading sideways. No
   * flex-direction changes, no transform math — the CSS spec does the
   * rotation natively.
   *
   * The .annotate-row / .find-row popouts revert to horizontal
   * writing-mode (they're real panels with horizontal text), and
   * re-anchor to the right edge of the strip instead of the bottom.
   */
  .ep-toolbar-wrap.focus {
    height: 100%;
    width: auto;
    border-right: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    /* `sideways-lr` rotates labels so the user tilts head to the LEFT
     * to read (text runs bottom-to-top). The fallback `vertical-rl`
     * reads top-to-bottom — WebKit/Tauri should pick sideways-lr but
     * older engines degrade gracefully to the other rotation. */
    writing-mode: vertical-rl;
    writing-mode: sideways-lr;
    /* In focus mode the TabBar (which is normally the window's drag
     * surface) is hidden. Make the whole vertical strip draggable so
     * the user can still move / snap the window. Individual buttons
     * opt out via `-webkit-app-region: no-drag` below so they stay
     * clickable. */
    -webkit-app-region: drag;
  }
  /* Buttons and interactive controls inside the focus-mode strip
     opt back out of the drag region — otherwise clicks become
     window-drag gestures. `.btn` covers every toolbar button
     (PREV, NEXT, FIT, ANNOTATE, FIND, EXIT FOCUS, every tool). */
  .ep-toolbar-wrap.focus .btn,
  .ep-toolbar-wrap.focus input,
  .ep-toolbar-wrap.focus select {
    -webkit-app-region: no-drag;
  }
  .ep-toolbar-wrap.focus .ep-toolbar {
    height: 100%;
    border-bottom: 0;
    overflow-x: visible;
    overflow-y: auto;
    /* Traffic-light clearance — vertical. `--tl-pad` (78px) is the
     * HORIZONTAL width of the traffic-light group; we only need
     * the dots' height (~14px) plus a small visual breathing band.
     * 36px sits the first toolbar item one comfortable line below
     * the dots without leaving an awkward empty strip.
     * `padding-top` is physical-top regardless of writing-mode, so
     * this works under sideways-lr too. */
    padding-top: 36px;
    box-sizing: border-box;
  }
  /* Hide the ⌘F kbd hint — reads awkwardly rotated; the title tooltip
     still surfaces the shortcut. */
  .ep-toolbar-wrap.focus .kbd {
    display: none;
  }
  /* Annotation popout: in focus mode it's a vertical column attached
     to the right edge of the main strip. We reset writing-mode to
     horizontal-tb here so the column lays out top-to-bottom in DOM
     order (the parent's sideways-lr would otherwise reverse it,
     putting the first tool at the bottom). The icons themselves are
     all symmetric SVGs so they don't need any rotation. */
  .ep-toolbar-wrap.focus .annotate-row {
    writing-mode: horizontal-tb;
    /* Panel itself reaches the top of the window so its background
     * is flush with the main strip's. Traffic-light clearance is
     * baked into the panel's own padding-top instead — that pushes
     * the icons down to a comfortable line below the dots without
     * leaving a strip of bare recess above the panel. */
    top: 0;
    left: 100%;
    right: auto;
    bottom: auto;
    width: auto;
    height: 100%;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    padding: 36px 6px 8px;
    border-bottom: 0;
    border-right: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
  }
  /* In a vertical column the inter-group separator becomes a thin
     horizontal rule. */
  .ep-toolbar-wrap.focus .annotate-row .tool-sep {
    width: 18px;
    height: 1px;
    margin: 4px 0;
  }
  /* Push the "Select text to highlight." hint to the bottom of the
     column and let it read horizontally. */
  .ep-toolbar-wrap.focus .annotate-row .annotate-hint {
    margin-top: auto;
    text-align: center;
    max-width: 64px;
    line-height: 1.25;
  }
  /* Find popout keeps horizontal writing-mode — it has a text input
     that doesn't fit a rotated layout. Anchor at the top of the
     strip; padding-top reserves the traffic-light clearance so the
     input doesn't sit under the dots while the panel itself still
     reaches the top of the window. */
  .ep-toolbar-wrap.focus .find-row {
    writing-mode: horizontal-tb;
    top: 0;
    left: 100%;
    right: auto;
    bottom: auto;
    width: 320px;
    height: auto;
    padding-top: 36px;
    border-bottom: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    border-right: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
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
  .btn.bookmark {
    color: var(--accent, #7a3a14);
  }

  /* Floating annotation bar — overlays the PDF area when toggled on,
     so opening it doesn't reflow / re-fit the viewport. Background
     matches the main toolbar (backdrop) so it reads as part of the
     toolbar surface rather than a separate panel. */
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
    background: var(--backdrop, #fcfaf5);
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
  /* Annotation-row tool buttons use inline SVG icons coloured via
     `currentColor`, so the button's text colour controls the icon —
     active state inverts to backdrop-on-ink and the outlines flip
     contrast automatically. */
  .tool-svg {
    width: 18px;
    height: 18px;
    display: block;
  }
  .btn.tool {
    padding: 4px 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  /* Visual separator between tool groups, matches design's |-divider. */
  .tool-sep {
    display: inline-block;
    width: 1px;
    height: 18px;
    background: var(--ink-12, rgba(26, 22, 18, 0.18));
    margin: 0 4px;
    flex-shrink: 0;
  }
  /* Highlight colour-picker stub: accent-coloured dot + dropdown caret. */
  .btn.tool-color {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 6px;
    opacity: 0.6;
    cursor: not-allowed;
  }
  .color-dot {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent, #7a3a14);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.25));
  }
  .color-caret {
    font-size: 9px;
    color: var(--ink-50, rgba(26, 22, 18, 0.5));
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

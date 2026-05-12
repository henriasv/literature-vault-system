<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { EditorState, EditorSelection } from "@codemirror/state";
  import { EditorView, keymap, highlightActiveLine, drawSelection } from "@codemirror/view";
  import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
  import { searchKeymap, highlightSelectionMatches, search } from "@codemirror/search";
  import { markdown } from "@codemirror/lang-markdown";
  import {
    HighlightStyle,
    syntaxHighlighting,
    defaultHighlightStyle,
    indentOnInput,
    bracketMatching,
  } from "@codemirror/language";
  import { tags as t } from "@lezer/highlight";
  import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { marked } from "marked";
  import { readNote, writeNote, setTags, splitNote, paperLabel, readAnnotations } from "../lib/vault";
  import {
    libraryState as libraryStateRef,
    paperByCitekey,
    allTags as allKnownTagsFn,
    patchPaperTags,
    refreshLibrary,
    toggleTagFilter,
  } from "../state/library.svelte";
  import { pdfNavState, requestJump, requestFlash } from "../state/pdfNav.svelte";

  let { citekey }: { citekey: string } = $props();

  const IDLE_SAVE_MS = 2000;

  let host: HTMLDivElement;
  let view: EditorView | null = null;

  /** Full file as last seen on disk (or last successfully written). Used to detect
   *  external changes vs our own write echoes. */
  let lastSaved = $state<string>("");
  let lastSavedAt = $state<number | null>(null);
  let saveError = $state<string | null>(null);
  let saving = $state(false);
  let dirty = $state(false);
  let loadError = $state<string | null>(null);
  let onDiskBanner = $state<{ contents: string } | null>(null);
  let idleTimer: number | null = null;
  let unlistenNoteChanged: UnlistenFn | null = null;

  /** Frontmatter block including both `---` fences and their newlines. The user
   *  doesn't see this in the editor; we re-attach it on every save. */
  let frontmatterRaw = $state("");
  /** Set when the file's frontmatter couldn't be parsed — editor falls back to
   *  raw-edit mode so the user can fix it manually. */
  let rawMode = $state(false);
  let detailsOpen = $state(false);

  /** Rendered ↔ raw ↔ annotations toggle for the body view.
   *   - rendered:    marked() HTML from the note body
   *   - raw:         CodeMirror editor
   *   - annotations: list of highlights + sticky notes from the sidecar JSON
   */
  let viewMode = $state<"rendered" | "raw" | "annotations">("rendered");
  /** Mirrors the editor doc so the rendered view recomputes when content changes. */
  let bodyText = $state("");

  /* ---- Annotations tab data ---------------------------------------------
   * Parsed AnnotationTransferItem[] from `Annotations/{citekey}.json`. We
   * re-fetch when citekey changes, when the tab becomes active, or when
   * `sidecarVersion` is bumped by EmbedPDFView after a save (so adding /
   * editing in the PDF pane refreshes the list reactively). */
  /* Numeric subtype IDs — kept inline to avoid pulling the EmbedPDF
   * runtime in here. Matches PdfAnnotationSubtype.HIGHLIGHT / .TEXT. */
  const HIGHLIGHT_SUBTYPE = 9;
  const STICKY_SUBTYPE = 1;

  interface AnnotationRow {
    id: string;
    pageIndex: number;            // 0-based
    kind: "highlight" | "sticky" | "other";
    color: string | null;
    excerpt: string;              // highlight only
    comment: string;              // user note (custom.comment for highlights, contents for stickies)
    /** Page-coord midpoint of the rect — passed as `pageCoordinates` to
     *  scrollToPage so the annotation lands at viewport centre. */
    center: { x: number; y: number } | null;
  }
  let annotationRows = $state<AnnotationRow[]>([]);
  let annotationsLoadError = $state<string | null>(null);

  async function loadAnnotations(ck: string): Promise<void> {
    try {
      const raw = await readAnnotations(ck);
      if (!raw || !raw.trim()) {
        annotationRows = [];
        annotationsLoadError = null;
        return;
      }
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        annotationRows = [];
        annotationsLoadError = "Sidecar JSON is not an array";
        return;
      }
      const rows: AnnotationRow[] = [];
      for (const item of parsed) {
        const a = item?.annotation;
        if (!a || typeof a.id !== "string") continue;
        const rect = a.rect;
        let center: { x: number; y: number } | null = null;
        if (
          rect && rect.origin && rect.size &&
          typeof rect.origin.x === "number" && typeof rect.origin.y === "number" &&
          typeof rect.size.width === "number" && typeof rect.size.height === "number"
        ) {
          center = {
            x: rect.origin.x + rect.size.width / 2,
            y: rect.origin.y + rect.size.height / 2,
          };
        }
        const kind: AnnotationRow["kind"] =
          a.type === HIGHLIGHT_SUBTYPE ? "highlight" :
          a.type === STICKY_SUBTYPE ? "sticky" : "other";
        const contentsStr = typeof a.contents === "string" ? a.contents : "";
        const customComment =
          (a.custom && typeof a.custom.comment === "string" && a.custom.comment) || "";
        const color =
          (typeof a.strokeColor === "string" && a.strokeColor) ||
          (typeof a.color === "string" && a.color) || null;
        rows.push({
          id: a.id,
          pageIndex: typeof a.pageIndex === "number" ? a.pageIndex : 0,
          kind,
          color: kind === "highlight" ? color : null,
          excerpt: kind === "highlight" ? contentsStr : "",
          comment: kind === "sticky" ? contentsStr : customComment,
          center,
        });
      }
      rows.sort((x, y) => x.pageIndex - y.pageIndex);
      annotationRows = rows;
      annotationsLoadError = null;
    } catch (e) {
      annotationsLoadError = String(e);
      annotationRows = [];
    }
  }

  $effect(() => {
    /* Refetch reactively: dep on citekey + viewMode + sidecarVersion. */
    const ck = citekey;
    void viewMode;
    void pdfNavState.sidecarVersion;
    void loadAnnotations(ck);
  });

  /* Single click = scroll + flash; double click = scroll + open menu.
   * Browsers fire two `click` events before `dblclick`, so the single-
   * click action runs twice when double-clicking — both produce the
   * same scroll-to-target and flash, which is fine. The dblclick handler
   * additionally fires selectAnnotation; by the time it does, the first
   * click already scrolled the page into the DOM. */
  function navigateTo(row: AnnotationRow, opts: { open: boolean }): void {
    requestJump(citekey, row.pageIndex + 1, {
      centerOn: row.center ?? undefined,
      openAnnotationId: opts.open ? row.id : undefined,
    });
  }
  function onAnnotationRowClick(row: AnnotationRow): void {
    navigateTo(row, { open: false });
    requestFlash(citekey, row.id);
  }
  function onAnnotationRowDblClick(row: AnnotationRow): void {
    navigateTo(row, { open: true });
  }

  marked.setOptions({ gfm: true, breaks: false });
  const renderedHtml = $derived(
    viewMode === "rendered" ? (marked.parse(bodyText) as string) : ""
  );

  const meta = $derived(paperByCitekey(citekey));
  const knownTags = $derived(allKnownTagsFn());

  // Inline tag-editor state.
  let addingTag = $state(false);
  let tagInputValue = $state("");
  let tagInputEl: HTMLInputElement | undefined = $state();
  let tagSaving = $state(false);
  let tagError = $state<string | null>(null);

  const authorTotal = $derived(meta ? meta.authorCount ?? meta.authors.length : 0);
  /** Show up to 10 names in the metadata header before falling back to
   *  "Lastname et al." Most papers fit; only mega-author HEP/biology
   *  papers actually need the truncation. */
  const AUTHOR_PREVIEW_LIMIT = 10;
  const authorPreview = $derived.by(() => {
    if (!meta || meta.authors.length === 0) return "";
    if (meta.authors.length <= AUTHOR_PREVIEW_LIMIT) return meta.authors.join(", ");
    const first = meta.authors[0].split(",")[0].trim();
    return `${first} et al.`;
  });
  const authorFull = $derived.by(() => {
    if (!meta || meta.authors.length === 0) return "";
    let full = meta.authors.join(", ");
    if (meta.authorCount && meta.authorCount > meta.authors.length) {
      full += ` …and ${meta.authorCount - meta.authors.length} others`;
    }
    return full;
  });

  function clearIdle() {
    if (idleTimer !== null) {
      window.clearTimeout(idleTimer);
      idleTimer = null;
    }
  }

  function reassemble(editorContent: string): string {
    return rawMode ? editorContent : frontmatterRaw + editorContent;
  }

  async function flushSave(): Promise<void> {
    clearIdle();
    if (!view) return;
    const editorContent = view.state.doc.toString();
    const fullText = reassemble(editorContent);
    if (fullText === lastSaved) {
      dirty = false;
      return;
    }
    saving = true;
    saveError = null;
    try {
      await writeNote(citekey, fullText);
      lastSaved = fullText;
      lastSavedAt = Date.now();
      dirty = false;
    } catch (e) {
      saveError = String(e);
    } finally {
      saving = false;
    }
  }

  function scheduleIdleSave() {
    clearIdle();
    idleTimer = window.setTimeout(() => {
      void flushSave();
    }, IDLE_SAVE_MS);
  }

  function formatTimestamp(d: Date = new Date()): string {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /** Append a fresh `### YYYY-MM-DD HH:MM` heading to the end of the note and place
   *  the cursor on a blank line below it. Triggered by ⌘⇧N (when the editor is
   *  focused) and by the inline status-bar button. */
  function insertTimestampSection(): boolean {
    if (!view) return false;
    const stamp = formatTimestamp();
    const docLen = view.state.doc.length;
    // Ensure exactly two newlines before the heading so it's visually separated.
    const tail = view.state.doc.sliceString(Math.max(0, docLen - 2), docLen);
    let prefix = "\n\n";
    if (tail.endsWith("\n\n")) prefix = "";
    else if (tail.endsWith("\n")) prefix = "\n";
    const insertion = `${prefix}### ${stamp}\n\n`;
    const cursorAt = docLen + insertion.length;
    view.dispatch({
      changes: { from: docLen, insert: insertion },
      selection: EditorSelection.cursor(cursorAt),
      scrollIntoView: true,
    });
    view.focus();
    return true;
  }

  function buildState(initial: string) {
    return EditorState.create({
      doc: initial,
      extensions: [
        history(),
        drawSelection(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        markdown(),
        search({ top: true }),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        /* Override the default heading rule. defaultHighlightStyle
         * applies `text-decoration: underline` to every `tags.heading*`
         * which renders as a thick black line under each ATX heading
         * in the markdown body. Bold weight alone is sufficient. */
        syntaxHighlighting(
          HighlightStyle.define([
            { tag: t.heading, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading1, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading2, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading3, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading4, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading5, fontWeight: "700", textDecoration: "none" },
            { tag: t.heading6, fontWeight: "700", textDecoration: "none" },
          ]),
        ),
        keymap.of([
          {
            key: "Mod-Shift-n",
            run: () => insertTimestampSection(),
            preventDefault: true,
          },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
        ]),
        EditorView.lineWrapping,
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            dirty = true;
            bodyText = u.state.doc.toString();
            scheduleIdleSave();
          }
        }),
        EditorView.domEventHandlers({
          blur: () => {
            void flushSave();
            return false;
          },
        }),
        EditorView.theme({
          "&": {
            height: "100%",
            fontSize: "14px",
            backgroundColor: "var(--surface)",
            color: "var(--fg)",
          },
          ".cm-scroller": {
            fontFamily: 'var(--serif)',
            lineHeight: "1.7",
          },
          ".cm-content": { padding: "20px 28px 32px" },
          ".cm-focused": { outline: "none" },
          ".cm-activeLine": { backgroundColor: "transparent" },
          ".cm-cursor": { borderLeftColor: "var(--accent)" },
          ".cm-selectionBackground, .cm-selectionMatch": {
            backgroundColor: "var(--surface-soft) !important",
          },
        }),
      ],
    });
  }

  async function loadInto(ck: string) {
    loadError = null;
    saveError = null;
    onDiskBanner = null;
    try {
      const text = await readNote(ck);
      const split = splitNote(text);
      if (split) {
        frontmatterRaw = split.frontmatter;
        rawMode = false;
        bodyText = split.body;
        if (view) view.setState(buildState(split.body));
      } else {
        // Frontmatter missing/malformed — let the user see and fix the whole file.
        frontmatterRaw = "";
        rawMode = true;
        bodyText = text;
        if (view) view.setState(buildState(text));
      }
      lastSaved = text;
      lastSavedAt = Date.now();
      dirty = false;
    } catch (e) {
      loadError = String(e);
    }
  }

  async function handleOnDiskChange() {
    if (!view) return;
    let onDisk: string;
    try {
      onDisk = await readNote(citekey);
    } catch (e) {
      console.warn(`re-read after note:changed failed for ${citekey}`, e);
      return;
    }
    if (onDisk === lastSaved) return; // our own write echo

    const inEditor = view.state.doc.toString();

    if (rawMode) {
      if (onDisk === inEditor) {
        lastSaved = onDisk;
        dirty = false;
        onDiskBanner = null;
        return;
      }
      if (!dirty) {
        lastSaved = onDisk;
        view.setState(buildState(onDisk));
        onDiskBanner = null;
        return;
      }
      onDiskBanner = { contents: onDisk };
      return;
    }

    const split = splitNote(onDisk);
    if (!split) {
      // Frontmatter went bad while we had this open — drop into raw mode.
      if (!dirty) {
        rawMode = true;
        frontmatterRaw = "";
        lastSaved = onDisk;
        view.setState(buildState(onDisk));
        onDiskBanner = null;
        return;
      }
      onDiskBanner = { contents: onDisk };
      return;
    }

    if (split.body === inEditor) {
      // Body unchanged on disk; only frontmatter (likely the agent re-filed). Sync silently.
      frontmatterRaw = split.frontmatter;
      lastSaved = onDisk;
      dirty = false;
      onDiskBanner = null;
      return;
    }
    if (!dirty) {
      // Editor is clean; pull both halves of the new disk content in silently.
      frontmatterRaw = split.frontmatter;
      lastSaved = onDisk;
      view.setState(buildState(split.body));
      onDiskBanner = null;
      return;
    }
    // Dirty + body diverged on disk → user decides.
    onDiskBanner = { contents: onDisk };
  }

  function reloadFromDisk() {
    if (!onDiskBanner || !view) return;
    const text = onDiskBanner.contents;
    const split = splitNote(text);
    if (split) {
      frontmatterRaw = split.frontmatter;
      rawMode = false;
      view.setState(buildState(split.body));
    } else {
      rawMode = true;
      frontmatterRaw = "";
      view.setState(buildState(text));
    }
    lastSaved = text;
    dirty = false;
    onDiskBanner = null;
  }

  function dismissBanner() {
    onDiskBanner = null;
  }

  onMount(() => {
    view = new EditorView({ parent: host, state: buildState("") });
    void loadInto(citekey);
    void (async () => {
      unlistenNoteChanged = await listen<{ citekey: string }>("note:changed", (event) => {
        if (event.payload.citekey !== citekey) return;
        void handleOnDiskChange();
      });
    })();
  });

  $effect(() => {
    const ck = citekey;
    untrack(() => {
      void (async () => {
        await flushSave();
        await loadInto(ck);
      })();
    });
  });

  onDestroy(() => {
    void flushSave();
    clearIdle();
    unlistenNoteChanged?.();
    unlistenNoteChanged = null;
    view?.destroy();
    view = null;
  });

  /** Apply a new tag list to the current paper:
   *   - flush any pending body edits first so set_tags doesn't read a stale body,
   *   - call the Rust set_tags command which atomically rewrites the YAML block,
   *   - update lastSaved + frontmatterRaw with the returned content so the
   *     subsequent note:changed event from the disk watcher is recognised as
   *     our own write echo (no banner flash),
   *   - patch libraryState optimistically so the header re-renders immediately,
   *     then kick a background refreshLibrary for any cross-cutting state
   *     (tag filters in the Library pane, etc.).
   */
  async function commitTags(newTags: string[]): Promise<void> {
    if (!meta) return;
    tagError = null;
    tagSaving = true;
    const ck = meta.citekey;
    const prevTags = meta.tags;
    patchPaperTags(ck, newTags);
    try {
      await flushSave();
      const newContent = await setTags(ck, newTags);
      const split = splitNote(newContent);
      if (split) frontmatterRaw = split.frontmatter;
      lastSaved = newContent;
      lastSavedAt = Date.now();
      void refreshLibrary();
    } catch (e) {
      tagError = String(e);
      patchPaperTags(ck, prevTags);
    } finally {
      tagSaving = false;
    }
  }

  function removeTag(tag: string): void {
    if (!meta || tagSaving) return;
    void commitTags(meta.tags.filter((t) => t !== tag));
  }

  function startAddTag(): void {
    if (tagSaving) return;
    addingTag = true;
    tagInputValue = "";
    tagError = null;
    setTimeout(() => tagInputEl?.focus(), 0);
  }

  function cancelAddTag(): void {
    addingTag = false;
    tagInputValue = "";
  }

  async function submitNewTag(): Promise<void> {
    const raw = tagInputValue.trim();
    if (!raw || !meta) {
      cancelAddTag();
      return;
    }
    if (meta.tags.includes(raw)) {
      cancelAddTag();
      return;
    }
    cancelAddTag();
    await commitTags([...meta.tags, raw]);
  }

  function onTagInputKey(e: KeyboardEvent): void {
    if (e.key === "Enter") {
      e.preventDefault();
      void submitNewTag();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelAddTag();
    }
  }

  function onTagInputBlur(): void {
    if (tagInputValue.trim()) {
      void submitNewTag();
    } else {
      cancelAddTag();
    }
  }

  function statusLabel(): string {
    if (saveError) return `error: ${saveError}`;
    if (saving) return "saving…";
    if (dirty) return "unsaved";
    if (lastSavedAt !== null) return "saved";
    return "";
  }
</script>

<div class="note-editor">
  {#if loadError}
    <div class="banner err">Failed to load note: {loadError}</div>
  {/if}
  {#if saveError}
    <div class="banner err">Save failed: {saveError}</div>
  {/if}
  {#if onDiskBanner}
    <div class="banner warn">
      <span>file changed on disk — your unsaved edits are still here</span>
      <span class="actions">
        <button onclick={reloadFromDisk}>Reload</button>
        <button onclick={dismissBanner}>Dismiss</button>
      </span>
    </div>
  {/if}

  {#if rawMode}
    <div class="banner muted">
      <span>raw mode — frontmatter couldn't be parsed; edit carefully</span>
    </div>
  {:else if meta}
    {@const entryNo = (() => {
      const idx = libraryStateRef.papers.findIndex((p) => p.citekey === meta.citekey);
      return idx >= 0 ? String(libraryStateRef.papers.length - idx).padStart(3, "0") : "—";
    })()}
    <header class="meta">
      <div class="masthead-row caps">
        <span>Entry</span>
        <span class="dot">·</span>
        <span>No. {entryNo}</span>
      </div>
      <h2 class="title">{meta.title}</h2>
      <div class="authors">
        <span class="author-name">{authorPreview}</span>{#if meta.authors.length > AUTHOR_PREVIEW_LIMIT || (meta.authorCount && meta.authorCount > meta.authors.length)} <span class="muted">({authorTotal} authors)</span>{/if}
      </div>
      <div class="venue">
        {#if meta.journal}<span class="journal">{meta.journal}</span> <span class="dot">·</span>{/if}
        <span class="year">{meta.year}</span>
        {#if meta.doi}
          <span class="dot">·</span>
          <a href={`https://doi.org/${meta.doi}`} target="_blank" rel="noopener">doi</a>
        {/if}
        {#if meta.arxivId}
          <span class="dot">·</span>
          <a href={`https://arxiv.org/abs/${meta.arxivId}`} target="_blank" rel="noopener">arxiv</a>
        {/if}
      </div>
      <div class="tags">
        {#each meta.tags as t (t)}
          {@const isFilterActive = libraryStateRef.selectedTags.includes(t)}
          <span class="tag" class:cite={t.startsWith("cite:")} class:filter-active={isFilterActive}>
            <button
              class="tag-text"
              onclick={() => toggleTagFilter(t)}
              title={isFilterActive
                ? `Click to remove "${t}" from the library tag filter`
                : `Click to filter the library by "${t}"`}>{t.replace(/^cite:/, "")}</button>
            <button
              class="tag-remove"
              onclick={() => removeTag(t)}
              disabled={tagSaving}
              title={`Remove tag "${t}"`}
              aria-label={`Remove tag ${t}`}>×</button>
          </span>
        {/each}
        {#if addingTag}
          <input
            type="text"
            class="tag-input"
            list="tag-suggestions"
            bind:value={tagInputValue}
            bind:this={tagInputEl}
            onkeydown={onTagInputKey}
            onblur={onTagInputBlur}
            placeholder="tag…"
            disabled={tagSaving}
          />
        {:else}
          <button
            class="tag-add"
            onclick={startAddTag}
            disabled={tagSaving}
            title="Add tag">+ tag</button>
        {/if}
        {#if tagError}
          <span class="tag-error" title={tagError}>! {tagError}</span>
        {/if}
      </div>
      <datalist id="tag-suggestions">
        {#each knownTags as t}
          <option value={t}></option>
        {/each}
      </datalist>
      <button class="details-toggle" onclick={() => (detailsOpen = !detailsOpen)}>
        {detailsOpen ? "▾" : "▸"} details
      </button>
      {#if detailsOpen}
        <div class="details">
          {#if meta.authors.length > AUTHOR_PREVIEW_LIMIT || (meta.authorCount && meta.authorCount > meta.authors.length)}
            <div class="row">
              <span class="label">authors</span>
              <span class="value">{authorFull}</span>
            </div>
          {/if}
          {#if meta.abstract}
            <div class="row">
              <span class="label">abstract</span>
              <p class="abstract">{meta.abstract}</p>
            </div>
          {/if}
          <div class="row">
            <span class="label">added</span>
            <span class="value">{meta.added}</span>
          </div>
          {#if meta.doi}
            <div class="row">
              <span class="label">doi</span>
              <span class="value mono">{meta.doi}</span>
            </div>
          {/if}
          {#if meta.arxivId}
            <div class="row">
              <span class="label">arxiv</span>
              <span class="value mono">{meta.arxivId}</span>
            </div>
          {/if}
          <div class="row">
            <span class="label">citekey</span>
            <span class="value mono">{meta.citekey}</span>
          </div>
          {#if meta.sha256Pdf}
            <div class="row">
              <span class="label">sha256</span>
              <span class="value mono short">{meta.sha256Pdf}</span>
            </div>
          {/if}
        </div>
      {/if}
    </header>
  {/if}

  {#if !rawMode}
    <div class="view-toggle">
      <button class:on={viewMode === "raw"} onclick={() => (viewMode = "raw")}>Edit</button>
      <button class:on={viewMode === "rendered"} onclick={() => (viewMode = "rendered")}>Preview</button>
      <button class:on={viewMode === "annotations"} onclick={() => (viewMode = "annotations")}>
        Annotations{#if annotationRows.length > 0} <span class="count">{annotationRows.length}</span>{/if}
      </button>
    </div>
  {/if}

  <div class="body-stack">
    {#if viewMode === "rendered" && !rawMode}
      <article class="rendered">
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html renderedHtml}
      </article>
    {/if}
    {#if viewMode === "annotations" && !rawMode}
      <div class="annotations-list">
        {#if annotationsLoadError}
          <div class="ann-error">Couldn't read annotation sidecar: {annotationsLoadError}</div>
        {:else if annotationRows.length === 0}
          <div class="ann-empty">No highlights or sticky notes yet. Select text or use the Annotate menu in the PDF.</div>
        {:else}
          {#each annotationRows as row (row.id)}
            <button
              type="button"
              class="ann-row"
              onclick={() => onAnnotationRowClick(row)}
              ondblclick={() => onAnnotationRowDblClick(row)}
              title="Click to jump · double-click to open"
            >
              {#if row.kind === "sticky"}
                <span class="ann-icon" aria-hidden="true">●</span>
              {:else}
                <span
                  class="ann-swatch"
                  style:background={row.color ?? "transparent"}
                  aria-hidden="true"
                ></span>
              {/if}
              <span class="ann-page">p.{row.pageIndex + 1}</span>
              <span class="ann-body">
                {#if row.kind === "highlight"}
                  {#if row.excerpt}
                    <span class="ann-excerpt">“{row.excerpt}”</span>
                  {:else}
                    <span class="ann-excerpt ann-excerpt-empty">(no excerpt)</span>
                  {/if}
                  {#if row.comment}
                    <span class="ann-comment">{row.comment}</span>
                  {/if}
                {:else if row.kind === "sticky"}
                  {#if row.comment}
                    <span class="ann-comment">{row.comment}</span>
                  {:else}
                    <span class="ann-excerpt ann-excerpt-empty">(empty note)</span>
                  {/if}
                {:else}
                  {#if row.comment}<span class="ann-comment">{row.comment}</span>{/if}
                {/if}
              </span>
            </button>
          {/each}
        {/if}
      </div>
    {/if}
    <div bind:this={host} class="cm-host" class:hidden={viewMode !== "raw" && !rawMode}></div>
  </div>

  <div class="status">
    <button
      class="shortcut-hint"
      onclick={insertTimestampSection}
      title="Append a new ### YYYY-MM-DD HH:MM section to the end of the note"
    >Timestamp <kbd>⌘⇧N</kbd></button>
    <span class="state" class:dirty class:err={!!saveError}>{statusLabel()}</span>
  </div>
</div>

<style>
  .note-editor {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--surface);
  }
  /* Note pane header — direction-b.jsx B_NotesPane:
     padding 20px 22px 18px, border-bottom 2px solid INK (heavy!) */
  .meta {
    padding: 20px 22px 18px;
    border-bottom: 2px solid var(--ink);
    flex-shrink: 0;
    overflow-y: auto;
    background: var(--panel);
  }
  /* Entry · No. 001 — Inter 9.5px, 700, accent, letter-spacing 1.6,
     uppercase, marginBottom 6 */
  .masthead-row {
    color: var(--accent);
    margin-bottom: 6px;
    display: flex;
    gap: 5px;
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
  }
  .masthead-row .dot {
    color: var(--accent);
  }
  /* Title — Source Serif Display, 17px, weight 700, ink, letter-spacing
     -0.4, line-height 1.2, marginBottom 10 */
  .meta .title {
    font-family: var(--serif);
    font-size: 17px;
    font-weight: 700;
    margin: 0 0 10px;
    line-height: 1.2;
    color: var(--ink);
    letter-spacing: -0.4px;
  }
  /* Authors — Source Serif italic 12px ink70, marginBottom 4 */
  .meta .authors {
    font-family: var(--serif);
    font-style: italic;
    font-size: 12px;
    color: var(--ink-70);
    margin-bottom: 4px;
  }
  /* Venue line — Inter 10.5px ink50 weight 500. Children override font:
     journal = Source Serif italic 12px ink70; year = tabular-nums Inter;
     "doi" = JetBrainsMono 10px accent. Dots ink30 with margin 0 6px. */
  .meta .venue {
    font-family: var(--sans);
    font-size: 10.5px;
    font-weight: 500;
    color: var(--ink-50);
    margin-bottom: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
  }
  .meta .venue .journal {
    font-family: var(--serif);
    font-style: italic;
    font-size: 12px;
    color: var(--ink-70);
  }
  .meta .venue .year {
    font-variant-numeric: tabular-nums;
  }
  .meta .venue .dot {
    color: var(--ink-30);
    margin: 0 6px;
  }
  .meta .venue a {
    color: var(--accent);
    font-family: var(--mono);
    font-size: 10px;
    text-decoration: none;
    text-transform: lowercase;
  }
  .meta .venue a:hover {
    text-decoration: underline;
  }
  .meta .muted {
    color: var(--muted);
  }
  .meta .tags {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
    margin-bottom: 4px;
  }
  .meta .tag {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    background: var(--surface-soft);
    border-radius: 2px;
    padding: 2px 4px 2px 8px;
    line-height: 1.4;
    color: var(--fg-soft);
  }
  .meta .tag.cite {
    border: 1px dashed var(--border-strong);
    background: transparent;
  }
  .tag-text {
    margin-right: 4px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    padding: 0;
    cursor: pointer;
  }
  .tag-text:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .meta .tag.filter-active {
    background: var(--accent);
    color: var(--panel);
  }
  .meta .tag.filter-active.cite {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--panel);
  }
  .meta .tag.filter-active .tag-remove {
    color: var(--panel);
  }
  .meta .tag.filter-active .tag-text:hover {
    color: var(--panel);
    text-decoration: underline;
  }
  .tag-remove {
    background: transparent;
    border: 0;
    color: var(--muted);
    font-size: 12px;
    line-height: 1;
    width: 14px;
    height: 14px;
    border-radius: 2px;
    padding: 0;
    cursor: pointer;
  }
  .tag-remove:hover:not(:disabled) {
    background: var(--border);
    color: var(--fg);
  }
  .tag-add {
    background: transparent;
    border: 1px dashed var(--border);
    color: var(--muted);
    font-size: 11px;
    border-radius: 3px;
    padding: 1px 6px;
    cursor: pointer;
  }
  .tag-add:hover:not(:disabled) {
    background: var(--hover);
    color: var(--fg);
    border-style: solid;
  }
  .tag-input {
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: 3px;
    color: var(--fg);
    font: inherit;
    font-size: 11px;
    padding: 1px 6px;
    min-width: 100px;
    max-width: 200px;
  }
  .tag-error {
    font-size: 11px;
    color: #c0392b;
  }
  .details-toggle {
    background: transparent;
    border: 0;
    padding: 2px 0;
    font-size: 11px;
    color: var(--muted);
    cursor: pointer;
  }
  .details-toggle:hover {
    color: var(--fg);
  }
  .details {
    margin-top: 4px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .details .row {
    display: grid;
    grid-template-columns: 80px 1fr;
    gap: 6px;
    font-size: 11.5px;
    align-items: start;
  }
  .details .label {
    color: var(--muted);
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.05em;
    padding-top: 2px;
  }
  .details .value {
    line-height: 1.4;
  }
  .abstract {
    font-size: 11.5px;
    color: var(--fg);
    line-height: 1.5;
    margin: 0;
    white-space: pre-wrap;
  }
  .mono {
    font-family: "SF Mono", Menlo, monospace;
    font-size: 11px;
    word-break: break-all;
  }
  .mono.short {
    color: var(--muted);
  }
  .body-stack {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
  }

  /* Rendered/Raw toggle — direction-b.jsx: padding 14px 22px 10px, gap 14,
     Inter 10px 600, letter-spacing 1.2, uppercase. Active gets 1.5px
     accent border-bottom with paddingBottom 3. */
  .view-toggle {
    flex: 0 0 auto;
    display: flex;
    align-items: baseline;
    gap: 14px;
    padding: 14px 22px 10px;
  }
  .view-toggle button {
    border: 0;
    background: transparent;
    padding: 0 0 3px;
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--ink-30);
    cursor: pointer;
    border-radius: 0;
    border-bottom: 1.5px solid transparent;
  }
  .view-toggle button:hover {
    color: var(--ink-70);
  }
  .view-toggle button.on {
    color: var(--ink);
    border-bottom-color: var(--accent);
  }
  .view-toggle .count {
    display: inline-block;
    margin-left: 4px;
    padding: 0 5px;
    font-size: 9px;
    font-weight: 700;
    color: var(--accent);
    background: var(--ink-08, rgba(26, 22, 18, 0.08));
    border-radius: 8px;
    letter-spacing: 0;
    vertical-align: 1px;
  }

  /* Annotations list — same horizontal padding as .rendered for visual
     alignment with Preview. Buttons are full-width rows. */
  .annotations-list {
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 6px 0 12px;
    background: var(--panel);
  }
  .ann-empty,
  .ann-error {
    padding: 14px 22px;
    font-family: var(--serif);
    font-style: italic;
    font-size: 12px;
    color: var(--ink-50, rgba(26, 22, 18, 0.55));
    line-height: 1.5;
  }
  .ann-error {
    color: #b03020;
    font-style: normal;
  }
  .ann-row {
    display: grid;
    grid-template-columns: 10px 36px 1fr;
    gap: 10px;
    align-items: start;
    width: 100%;
    box-sizing: border-box;
    padding: 8px 22px;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    font: inherit;
    color: var(--ink);
    border-bottom: 1px solid var(--ink-08, rgba(26, 22, 18, 0.06));
  }
  .ann-row:hover {
    background: var(--hover, rgba(26, 22, 18, 0.04));
  }
  .ann-row:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  .ann-swatch {
    width: 10px;
    height: 10px;
    margin-top: 4px;
    border-radius: 50%;
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
  }
  .ann-icon {
    width: 10px;
    margin-top: 1px;
    text-align: center;
    color: #FFCD45;
    font-size: 14px;
    line-height: 1;
  }
  .ann-page {
    font-family: var(--sans);
    font-size: 10.5px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.4px;
    padding-top: 2px;
    font-variant-numeric: tabular-nums;
  }
  .ann-body {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .ann-excerpt {
    font-family: var(--serif);
    font-style: italic;
    font-size: 11.5px;
    line-height: 1.45;
    color: var(--ink-70, rgba(26, 22, 18, 0.78));
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .ann-excerpt-empty {
    font-style: italic;
    color: var(--ink-30, rgba(26, 22, 18, 0.35));
  }
  .ann-comment {
    font-family: var(--serif);
    font-size: 12px;
    line-height: 1.5;
    color: var(--ink);
    white-space: pre-wrap;
  }

  .cm-host {
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
  }
  .cm-host.hidden {
    display: none;
  }
  .cm-host :global(.cm-editor) {
    height: 100%;
  }

  /* Rendered markdown — direction-b.jsx NotesRendered:
     - h1: 17px weight 600 line-height 1.3 ink letter-spacing -0.2 margin 0 0 14
     - h2: 11px weight 700 letter-spacing 0.8 uppercase accent margin 20px 0 8px
     - p:  12px line-height 1.6 ink margin 0 0 10
     - ul: list-style none padding-left 0 margin 0 0 12
     - li: 12px line-height 1.55 ink relative padding-left 14 margin-bottom 6
       with accent · bullet at left 2 top 0 */
  .rendered {
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 8px 22px 20px;
    background: var(--panel);
    font-family: var(--serif);
    font-size: 12px;
    line-height: 1.6;
    color: var(--ink);
  }
  .rendered :global(h1) {
    font-family: var(--serif);
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -0.2px;
    line-height: 1.3;
    color: var(--ink);
    margin: 0 0 14px;
  }
  .rendered :global(h2) {
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--accent);
    margin: 20px 0 8px;
  }
  .rendered :global(h3) {
    font-family: var(--serif);
    font-size: 13px;
    font-weight: 700;
    color: var(--ink);
    margin: 16px 0 6px;
  }
  .rendered :global(p) {
    font-family: var(--serif);
    font-size: 12px;
    line-height: 1.6;
    color: var(--ink);
    margin: 0 0 10px;
  }
  .rendered :global(ul), .rendered :global(ol) {
    list-style: none;
    padding-left: 0;
    margin: 0 0 12px;
  }
  .rendered :global(li) {
    position: relative;
    padding-left: 14px;
    margin-bottom: 6px;
    font-family: var(--serif);
    font-size: 12px;
    line-height: 1.55;
    color: var(--ink);
  }
  .rendered :global(ul li::before) {
    content: "·";
    position: absolute;
    left: 2px;
    top: 0;
    color: var(--accent);
    font-weight: 700;
  }
  .rendered :global(ol) {
    counter-reset: ol-counter;
  }
  .rendered :global(ol li) {
    counter-increment: ol-counter;
  }
  .rendered :global(ol li::before) {
    content: counter(ol-counter) ".";
    position: absolute;
    left: 0;
    top: 0;
    color: var(--accent);
    font-weight: 600;
  }
  .rendered :global(a) {
    color: var(--accent);
    text-decoration: underline;
  }
  .rendered :global(code) {
    font-family: var(--mono);
    font-size: 11px;
    background: var(--panel-alt);
    padding: 1px 4px;
    border-radius: 0;
  }
  .rendered :global(pre) {
    background: var(--panel-alt);
    padding: 10px 12px;
    border-radius: 0;
    overflow-x: auto;
    margin: 0 0 12px;
  }
  .rendered :global(pre code) {
    background: transparent;
    padding: 0;
  }
  .rendered :global(blockquote) {
    border-left: 2px solid var(--accent);
    margin: 0 0 12px;
    padding-left: 12px;
    color: var(--ink-70);
    font-style: italic;
  }
  .rendered :global(hr) {
    border: 0;
    border-top: 1px solid var(--ink-12);
    margin: 18px 0;
  }
  .rendered :global(em) {
    font-style: italic;
  }
  .rendered :global(strong) {
    font-weight: 700;
  }
  /* Footer — direction-b.jsx: padding 12px 22px, border-top 1px ink12,
     Inter 10px ink50 letter-spacing 0.6 uppercase 600. "+" in accent.
     "saved" overrides to italic Source Serif text-transform none ink30. */
  .status {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-family: var(--sans);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-weight: 600;
    color: var(--ink-50);
    padding: 12px 22px;
    border-top: 1px solid var(--ink-12);
    background: var(--panel);
  }
  .shortcut-hint {
    background: transparent;
    border: 0;
    padding: 0;
    color: var(--ink-50);
    font: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .shortcut-hint::before {
    content: "+";
    color: var(--accent);
    font-weight: 700;
  }
  .shortcut-hint:hover {
    color: var(--ink);
  }
  .shortcut-hint kbd {
    font-family: var(--mono);
    font-size: 9px;
    color: var(--ink-50);
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    margin-left: 4px;
  }
  .state {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    font-style: italic;
    font-family: var(--serif);
    color: var(--ink-30);
  }
  .state.dirty {
    color: var(--warning);
    font-style: normal;
  }
  .state.err {
    color: var(--accent);
    font-style: normal;
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
  .banner.warn {
    background: #fff5e0;
    color: #6c4a0e;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .banner.muted {
    color: var(--muted);
    background: var(--hover);
  }
  .banner .actions {
    display: flex;
    gap: 4px;
  }
  .banner button {
    padding: 2px 8px;
    font-size: 11px;
  }
  @media (prefers-color-scheme: dark) {
    .banner.err {
      background: #3a1813;
      color: #ffb1a3;
    }
    .banner.warn {
      background: #3a2e10;
      color: #ffd590;
    }
  }
</style>

<!--
  ReidentifyModal — for filed papers, mirrors InboxFindModal's UX:
  PDF preview on the left, CrossRef search + candidate list on the right.

  Opened from the right-click "Re-identify with CrossRef…" item. Pre-fills
  Title/First-author/Year from the current note's frontmatter so the user
  doesn't retype known data — usually they're correcting a *wrong* CrossRef
  match, not searching from scratch.

  Backend wire today is `reassign_with_doi(citekey, new_doi)` — currently a
  stub that returns an explanatory error. The full rename + frontmatter +
  note-body-preserve + index/library/Collections-refs update is the next
  meaningful chunk; this modal puts the UI in place so we can iterate.
-->
<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { TextLayer } from "pdfjs-dist";
  import { loadPdf, pdfUrlForPath, type PDFDocumentProxy } from "../lib/pdf";
  import {
    searchCrossref,
    pdfPathFor,
    reassignWithDoi,
    reassignWithBibtex,
    extractIdsFromPdf,
    type CrossrefCandidate,
    type ExtractedIds,
  } from "../lib/vault";
  import { paperByCitekey } from "../state/library.svelte";
  import { toast } from "../state/toast.svelte";
  import { closeReidentify } from "../state/reidentify.svelte";
  import { bibtexTemplates, findTemplate } from "../lib/bibtex-templates";

  type Props = { citekey: string };
  let { citekey }: Props = $props();

  /* Three identification paths:
   *   - "detect" — re-run `extract_ids.py` on the existing PDF (DOI / arXiv
   *     id from the file itself; useful when an agent guessed wrong and the
   *     PDF actually has a clean identifier in its metadata/text).
   *   - "search" — CrossRef title/author search (default, most common case).
   *   - "manual" — type the BibTeX entry directly (books, theses, etc.).
   */
  let mode = $state<"detect" | "search" | "manual">("search");

  /* Manual-entry state — template picker + the editable BibTeX body. */
  let templateType = $state(bibtexTemplates[0].type);
  let manualBibtex = $state(bibtexTemplates[0].template);
  let manualSubmitting = $state(false);
  let manualTouched = false; // user edited the textarea — avoid clobbering
  function selectTemplate(type: string) {
    templateType = type;
    const t = findTemplate(type);
    if (!t) return;
    if (manualTouched && !window.confirm("Replace your edits with the selected template?")) return;
    manualBibtex = t.template;
    manualTouched = false;
  }
  async function submitManual() {
    if (manualSubmitting) return;
    manualSubmitting = true;
    try {
      await reassignWithBibtex(citekey, manualBibtex);
      toast.info(`Reassigned ${citekey} from manual BibTeX`);
      closeReidentify();
    } catch (e) {
      toast.error(String(e));
    } finally {
      manualSubmitting = false;
    }
  }

  /* --- auto-detect (extract_ids.py on the existing PDF) --- */
  let detectResult = $state<ExtractedIds | null>(null);
  let detectError = $state<string | null>(null);
  let detecting = $state(false);
  async function runDetect() {
    if (detecting || !pdfPath) return;
    detecting = true;
    detectError = null;
    try {
      detectResult = await extractIdsFromPdf(pdfPath);
    } catch (e) {
      detectError = String(e);
      detectResult = null;
    } finally {
      detecting = false;
    }
  }
  async function fileFromDetect() {
    if (!detectResult?.doi && !detectResult?.arxivId) return;
    /* Refuse if the detected DOI matches the existing one — re-running would
     * be a no-op rename. Tell the user instead of silently doing nothing. */
    if (detectResult.doi && meta?.doi && detectResult.doi === meta.doi) {
      toast.info("Detected DOI matches the current one — already correct");
      return;
    }
    /* The Rust reassign command currently only takes a DOI; arXiv routing is
     * a TODO (the script needs an --arxiv variant). For now we prefer DOI; if
     * only arXiv was found, surface a notice. */
    if (detectResult.doi) {
      try {
        await reassignWithDoi(citekey, detectResult.doi);
        toast.info(`Reassigned ${citekey} → ${detectResult.doi}`);
        closeReidentify();
      } catch (e) {
        toast.error(String(e));
      }
    } else if (detectResult.arxivId) {
      toast.info(
        `Found arXiv id ${detectResult.arxivId} — reassignment by arXiv id is not yet wired (only DOI). Use Manual BibTeX or do a CrossRef search.`,
      );
    }
  }

  /* --- pre-populate from existing frontmatter --- */
  const meta = $derived(paperByCitekey(citekey));
  let title = $state("");
  let author = $state("");
  let year = $state("");
  let seeded = false;
  $effect(() => {
    if (seeded || !meta) return;
    title = meta.title ?? "";
    const a = meta.authors?.[0] ?? "";
    /* "Last, First" → "Last"; "First Last" → last token. CrossRef matches on
     * surname so we strip the rest. */
    if (a.includes(",")) author = a.split(",")[0].trim();
    else author = a.split(/\s+/).pop() ?? "";
    year = meta.year != null ? String(meta.year) : "";
    seeded = true;
  });

  /* --- search state (local — not shared with inbox per-path state) ---
   *
   * `searchToken` increments on each kicked-off search; the running async
   * awaits its result and only updates UI state if its token still matches
   * `activeSearchToken`. Cancel = clear `activeSearchToken` → the in-flight
   * subprocess keeps running on the Rust side (and CrossRef finishes) but
   * its result is discarded. */
  let candidates = $state<CrossrefCandidate[]>([]);
  let searching = $derived(activeSearchToken !== null);
  let activeSearchToken = $state<number | null>(null);
  let searchToken = 0;
  let searchError = $state<string | null>(null);
  let busyReassigning = $state(false);

  /* Selection is decoupled from the filing action — clicking a candidate
   * highlights it; the user then commits with the Reassign button. Prevents
   * a misclick from immediately rewriting the paper's files. */
  let selectedDoi = $state<string | null>(null);
  let selectedCand = $derived(
    selectedDoi ? candidates.find((c) => c.doi === selectedDoi) ?? null : null,
  );

  async function runSearch() {
    if (searching) return;
    const myToken = ++searchToken;
    activeSearchToken = myToken;
    searchError = null;
    try {
      const y = year.trim() ? parseInt(year.trim(), 10) : undefined;
      if (y !== undefined && Number.isNaN(y)) {
        if (activeSearchToken === myToken) searchError = "Year must be a number";
        return;
      }
      const result = await searchCrossref({
        title: title.trim() || undefined,
        author: author.trim() || undefined,
        year: y,
      });
      if (activeSearchToken !== myToken) return; // cancelled or superseded
      candidates = result;
      if (result.length === 0) searchError = "No matches from CrossRef";
    } catch (e) {
      if (activeSearchToken !== myToken) return;
      searchError = String(e);
      candidates = [];
    } finally {
      if (activeSearchToken === myToken) activeSearchToken = null;
    }
  }

  function cancelSearch() {
    activeSearchToken = null;
  }

  async function pickCandidate(doi: string) {
    if (busyReassigning) return;
    busyReassigning = true;
    try {
      await reassignWithDoi(citekey, doi);
      toast.info(`Reassigned ${citekey} → ${doi}`);
      closeReidentify();
    } catch (e) {
      toast.error(String(e));
    } finally {
      busyReassigning = false;
    }
  }

  /* --- PDF preview (same shape as InboxFindModal but resolves PDF by
   * citekey rather than by inbox path) --- */
  let pdfPath = $state<string | null>(null);
  let doc = $state<PDFDocumentProxy | null>(null);
  let docError = $state<string | null>(null);
  let pageNum = $state(1);
  let totalPages = $derived(doc?.numPages ?? 0);
  let canvas: HTMLCanvasElement | undefined = $state();
  let canvasWrap: HTMLDivElement | undefined = $state();
  let textLayerEl: HTMLDivElement | undefined = $state();
  let renderToken = 0;

  onMount(() => {
    void (async () => {
      try {
        pdfPath = await pdfPathFor(citekey);
        if (!pdfPath) {
          docError = "No PDF on disk for this citekey";
          return;
        }
        const url = pdfUrlForPath(pdfPath);
        doc = await loadPdf(url);
      } catch (e) {
        docError = String(e);
      }
    })();
  });

  onDestroy(() => {
    void doc?.destroy?.();
    doc = null;
  });

  $effect(() => {
    const d = doc;
    const p = pageNum;
    const wrap = canvasWrap;
    const cnv = canvas;
    if (!d || !cnv || !wrap) return;
    const myToken = ++renderToken;
    void (async () => {
      try {
        const page = await d.getPage(p);
        if (myToken !== renderToken) return;
        const viewport0 = page.getViewport({ scale: 1 });
        const availableWidth = untrack(() => wrap.clientWidth) || 600;
        const scale = (availableWidth - 8) / viewport0.width;
        const viewport = page.getViewport({ scale });
        const dpr = window.devicePixelRatio || 1;
        cnv.width = Math.floor(viewport.width * dpr);
        cnv.height = Math.floor(viewport.height * dpr);
        cnv.style.width = `${viewport.width}px`;
        cnv.style.height = `${viewport.height}px`;
        const ctx = cnv.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await page.render({ canvas: cnv, canvasContext: ctx, viewport }).promise;
        if (myToken !== renderToken) return;
        /* Text layer — invisible overlay of positioned <span>s that lets the
         * user click-and-drag select PDF text and copy it. Same pattern as
         * PDFView.svelte (pdfjs's TextLayer rendered into a div sized to the
         * viewport). */
        if (textLayerEl) {
          textLayerEl.replaceChildren();
          textLayerEl.style.width = `${viewport.width}px`;
          textLayerEl.style.height = `${viewport.height}px`;
          textLayerEl.style.setProperty("--scale-factor", String(viewport.scale));
          try {
            const layer = new TextLayer({
              textContentSource: page.streamTextContent(),
              container: textLayerEl,
              viewport,
            });
            await layer.render();
          } catch (e) {
            const msg = String(e);
            if (!msg.includes("ancel")) {
              console.warn("text layer render failed", e);
            }
          }
        }
      } catch (e) {
        if (myToken === renderToken) docError = String(e);
      }
    })();
  });

  function setPage(n: number) {
    if (!doc) return;
    pageNum = Math.max(1, Math.min(doc.numPages, n));
  }

  function cancel() {
    closeReidentify();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="modal-backdrop" onclick={cancel} role="presentation">
  <div
    class="modal"
    role="dialog"
    aria-modal="true"
    aria-label="Re-identify paper"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="hdr">
      <div class="hdr-left">
        <p class="caps">Re-identify · pick the correct CrossRef record</p>
        <p class="filename mono" title={citekey}>{citekey}</p>
      </div>
      <button class="close" onclick={cancel} aria-label="Close">×</button>
    </header>

    <div class="body">
      <section class="pdf-side" bind:this={canvasWrap}>
        {#if docError}
          <div class="err">Couldn't open PDF: {docError}</div>
        {:else if !doc}
          <div class="loading">Loading…</div>
        {:else}
          <div class="page-wrap">
            <canvas bind:this={canvas}></canvas>
            <div bind:this={textLayerEl} class="textLayer"></div>
          </div>
          <div class="page-nav">
            <button onclick={() => setPage(pageNum - 1)} disabled={pageNum <= 1}>‹</button>
            <span class="page-num">
              <span class="mono">{pageNum}</span>
              <span class="dim">/</span>
              <span class="mono dim">{totalPages}</span>
            </span>
            <button onclick={() => setPage(pageNum + 1)} disabled={pageNum >= totalPages}>›</button>
          </div>
        {/if}
      </section>

      <section class="form-side">
        <!-- Compact "current match" — single-card anchor for the sanity
             check (does this PDF really belong to the citekey on file?). One
             title line, one meta line; folds open into a slightly taller
             form when collapsed=false (kept compact by default). -->
        {#if meta}
          <details class="current-card">
            <summary>
              <span class="caps">Current</span>
              <span class="current-title-inline">{meta.title}</span>
              <span class="current-meta-inline">
                <span class="dim">·</span>
                <em>{(meta.authors?.[0] ?? "—").split(",")[0]}</em>
                <span class="dim">·</span>
                <span class="mono">{meta.year ?? "—"}</span>
              </span>
            </summary>
            <div class="current-detail">
              {#if meta.journal}<span>{meta.journal}</span>{/if}
              {#if meta.doi}
                <span class="dim">·</span> <span class="mono">{meta.doi}</span>
              {:else if meta.arxivId}
                <span class="dim">·</span> <span class="mono">arXiv:{meta.arxivId}</span>
              {/if}
            </div>
          </details>
        {/if}

        <div class="mode-tabs" role="tablist">
          <button
            class:on={mode === "detect"}
            onclick={() => (mode = "detect")}
            role="tab"
            aria-selected={mode === "detect"}
            title="Re-run extract_ids.py on the existing PDF"
          >Auto-detect</button>
          <button
            class:on={mode === "search"}
            onclick={() => (mode = "search")}
            role="tab"
            aria-selected={mode === "search"}
            title="Search CrossRef by title / author / year"
          >CrossRef search</button>
          <button
            class:on={mode === "manual"}
            onclick={() => (mode = "manual")}
            role="tab"
            aria-selected={mode === "manual"}
            title="Type the BibTeX entry directly"
          >Manual BibTeX</button>
        </div>

        {#if mode === "detect"}
          <p class="caps form-eyebrow">Re-run identifier extraction on the PDF</p>
          <p class="manual-prose">
            Scans the PDF for a DOI or arXiv id (metadata → text → raw bytes,
            cheap-to-expensive). Useful when the agent originally picked the
            wrong CrossRef record but the PDF itself contains a clean
            identifier.
          </p>
          <div class="search-row">
            <button
              class="search-go"
              class:searching={detecting}
              disabled={detecting}
              onclick={runDetect}
            >
              {#if detecting}
                <span class="spinner" aria-hidden="true"></span>
                Scanning PDF…
              {:else}
                {detectResult ? "Scan again" : "Scan the PDF"}
              {/if}
            </button>
          </div>
          {#if detectError}
            <p class="search-err">{detectError}</p>
          {/if}
          {#if detectResult}
            <div class="detect-result">
              <p class="caps form-eyebrow">Result · source: <span class="mono">{detectResult.source}</span></p>
              <p class="detect-line">
                <span class="caps-label">DOI</span>
                {#if detectResult.doi}
                  <span class="mono">{detectResult.doi}</span>
                  {#if detectResult.doi === meta?.doi}
                    <span class="dim">— same as current</span>
                  {/if}
                {:else}
                  <span class="dim">not found</span>
                {/if}
              </p>
              <p class="detect-line">
                <span class="caps-label">arXiv</span>
                {#if detectResult.arxivId}
                  <span class="mono">{detectResult.arxivId}</span>
                {:else}
                  <span class="dim">not found</span>
                {/if}
              </p>
              {#if detectResult.doi || detectResult.arxivId}
                <button class="search-go" onclick={fileFromDetect}>
                  File with this identifier
                </button>
              {:else}
                <p class="manual-hint">
                  No identifier found in the PDF. Try
                  <button class="link" onclick={() => (mode = "search")}>CrossRef search</button> or
                  <button class="link" onclick={() => (mode = "manual")}>Manual BibTeX</button>.
                </p>
              {/if}
            </div>
          {/if}
        {:else if mode === "search"}
          <div class="form-grid">
            <label>
              <span class="caps-label">Title</span>
              <input
                type="text"
                bind:value={title}
                placeholder="Paper title or fragment"
                onkeydown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
              />
            </label>
            <label>
              <span class="caps-label">First author</span>
              <input
                type="text"
                bind:value={author}
                placeholder="Surname"
                onkeydown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
              />
            </label>
            <label>
              <span class="caps-label">Year</span>
              <input
                type="text"
                inputmode="numeric"
                bind:value={year}
                placeholder="2024"
                onkeydown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
              />
            </label>
          </div>

          <div class="search-row">
            <button
              class="search-go"
              class:searching
              disabled={searching}
              onclick={runSearch}
            >
              {#if searching}
                <span class="spinner" aria-hidden="true"></span>
                Searching CrossRef…
              {:else}
                Search CrossRef
              {/if}
            </button>
            {#if searching}
              <button class="search-cancel" onclick={cancelSearch}>Cancel</button>
            {/if}
          </div>

          {#if searchError}
            <p class="search-err">{searchError}</p>
          {/if}

          {#if candidates.length > 0}
            <p class="caps form-eyebrow candidates-hdr">Candidates ({candidates.length})</p>
            <ul class="candidates">
              {#each candidates as c, ci (c.doi ?? `none-${ci}`)}
                <li>
                  <button
                    class="cand"
                    class:selected={c.doi && selectedDoi === c.doi}
                    disabled={!c.doi || busyReassigning}
                    onclick={() => c.doi && (selectedDoi = c.doi)}
                    title={c.doi ? "Select; click Reassign below to commit" : "Candidate has no DOI"}
                  >
                    <div class="cand-title">{c.title ?? "(untitled)"}</div>
                    <div class="cand-meta">
                      <span>{c.firstAuthor ?? "—"}</span>
                      {#if c.nAuthors && c.nAuthors > 1}
                        <span class="dim">+{c.nAuthors - 1}</span>
                      {/if}
                      <span class="dim">·</span>
                      <span class="mono">{c.year ?? "—"}</span>
                      <span class="dim">·</span>
                      <span class="mono dim doi">{c.doi ?? "no DOI"}</span>
                      {#if c.score !== null && c.score !== undefined}
                        <span class="grow"></span>
                        <span class="mono dim score">score {c.score.toFixed(1)}</span>
                      {/if}
                    </div>
                  </button>
                </li>
              {/each}
            </ul>

            <!-- Commit button — only enabled when a candidate is selected.
                 Decoupling click-to-select from click-to-commit means a
                 misclick doesn't rewrite the paper's files. -->
            <div class="commit-row">
              <button
                class="search-go"
                disabled={!selectedDoi || busyReassigning}
                onclick={() => selectedDoi && pickCandidate(selectedDoi)}
                title={selectedDoi
                  ? `Reassign ${citekey} → ${selectedDoi}`
                  : "Select a candidate above first"}
              >
                {#if busyReassigning}
                  <span class="spinner" aria-hidden="true"></span>
                  Reassigning…
                {:else if selectedCand}
                  Reassign as <span class="commit-doi mono">{selectedCand.doi}</span>
                {:else}
                  Reassign (select a candidate)
                {/if}
              </button>
            </div>
          {/if}

        {:else}
          <p class="caps form-eyebrow">Enter the BibTeX entry directly</p>
          <p class="manual-prose">
            For books, theses, preprints without DOIs, web pages, and anything
            else CrossRef doesn't have. Pick a template, fill the placeholders,
            and the note will be regenerated from these fields (the body of the
            existing note is preserved).
          </p>

          <label class="template-row">
            <span class="caps-label">Template</span>
            <select
              bind:value={templateType}
              onchange={() => selectTemplate(templateType)}
            >
              {#each bibtexTemplates as t (t.label)}
                <option value={t.type}>{t.label}</option>
              {/each}
            </select>
          </label>

          <textarea
            class="bibtex-area"
            bind:value={manualBibtex}
            oninput={() => (manualTouched = true)}
            spellcheck="false"
            rows="14"
          ></textarea>

          {#if findTemplate(templateType)?.hint}
            <p class="template-hint">{findTemplate(templateType)?.hint}</p>
          {/if}

          <button
            class="search-go"
            disabled={manualSubmitting || !manualBibtex.trim()}
            onclick={submitManual}
          >
            {manualSubmitting ? "Submitting…" : "File with this BibTeX"}
          </button>
        {/if}
      </section>
    </div>

    <footer class="ftr">
      <button class="ghost" onclick={cancel}>Cancel · keep as {citekey}</button>
    </footer>
  </div>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(26, 22, 18, 0.42);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    padding: 32px;
  }
  .modal {
    width: min(1180px, 100%);
    height: min(820px, 100%);
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow:
      0 1px 0 rgba(0, 0, 0, 0.02),
      0 24px 60px -20px rgba(26, 22, 18, 0.45);
  }
  .hdr {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--backdrop, #fcfaf5);
  }
  .hdr-left { display: flex; flex-direction: column; gap: 4px; }
  .hdr-left .caps { color: var(--accent, #7a3a14); margin: 0; }
  .filename { font-size: 12px; color: var(--ink-70); margin: 0; }
  .close {
    appearance: none;
    background: transparent;
    border: 0;
    cursor: pointer;
    font-size: 22px;
    line-height: 1;
    color: var(--ink-50);
    padding: 4px 8px;
    border-radius: 3px;
  }
  .close:hover { background: var(--ink-07); color: var(--ink); }

  .body {
    flex: 1 1 auto;
    display: grid;
    grid-template-columns: 1.1fr 1fr;
    min-height: 0;
  }
  .pdf-side {
    border-right: 1px solid var(--ink-12);
    background: var(--recess, #e6dfc8);
    padding: 16px;
    display: flex;
    flex-direction: column;
    align-items: center;
    overflow: auto;
    position: relative;
  }
  .page-wrap {
    position: relative;
    display: inline-block;
    box-shadow: 0 4px 16px -4px rgba(26, 22, 18, 0.18);
  }
  .pdf-side canvas {
    background: white;
    display: block;
  }
  /* Invisible text layer — same shape as PDFView's. The <span>s positioned
     here cover the canvas so click-drag selection works and ⌘C copies the
     underlying text content. */
  .textLayer {
    position: absolute;
    inset: 0;
    text-align: initial;
    overflow: clip;
    opacity: 1;
    line-height: 1;
    -webkit-text-size-adjust: none;
    text-size-adjust: none;
    transform-origin: 0 0;
    caret-color: CanvasText;
    z-index: 1;
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
  .pdf-side .err,
  .pdf-side .loading {
    margin: auto;
    color: var(--ink-50);
    font-size: 13px;
  }
  .page-nav {
    position: sticky;
    bottom: 0;
    margin-top: 12px;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: var(--panel);
    border: 1px solid var(--ink-12);
    border-radius: 999px;
    padding: 4px 10px;
    box-shadow: 0 2px 10px -4px rgba(26, 22, 18, 0.18);
  }
  .page-nav button {
    appearance: none;
    border: 0;
    background: transparent;
    cursor: pointer;
    font-size: 18px;
    color: var(--accent);
    padding: 2px 6px;
    border-radius: 3px;
  }
  .page-nav button:hover:not(:disabled) { background: var(--ink-07); }
  .page-nav button:disabled { color: var(--ink-30); cursor: default; }
  .page-num { font-size: 12px; color: var(--ink-70); }

  .form-side {
    padding: 16px 20px;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .form-eyebrow { color: var(--accent); margin: 0 0 8px; }
  .candidates-hdr { margin-top: 14px; }

  /* Compact "current match" — single-line summary with a fold-out for the
     journal + DOI line. Keeps the right pane uncluttered when the user just
     wants to compare against candidates at a glance. */
  .current-card {
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    background: var(--panel-alt, #f6f1e6);
    padding: 6px 10px;
    margin-bottom: 12px;
    font-size: 12.5px;
  }
  .current-card > summary {
    list-style: none;
    cursor: pointer;
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: nowrap;
    min-width: 0;
  }
  .current-card > summary::-webkit-details-marker { display: none; }
  .current-card > summary::after {
    content: "▸";
    margin-left: auto;
    color: var(--ink-30);
    flex: 0 0 auto;
    font-size: 10px;
  }
  .current-card[open] > summary::after { content: "▾"; }
  .current-card .caps {
    color: var(--accent);
    flex: 0 0 auto;
    font-size: 10px;
  }
  .current-title-inline {
    font-family: var(--serif);
    font-size: 13px;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1 1 auto;
  }
  .current-meta-inline {
    flex: 0 0 auto;
    color: var(--ink-70);
    font-size: 11.5px;
  }
  .current-detail {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px dashed var(--ink-12);
    font-size: 11.5px;
    color: var(--ink-70);
    word-break: break-all;
  }
  .current-detail .mono { font-size: 11px; }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 12px;
    margin-bottom: 12px;
  }
  .form-grid label:first-child { grid-column: 1 / -1; }
  .form-grid label { display: flex; flex-direction: column; gap: 4px; }
  .caps-label {
    font-family: var(--sans);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--ink-50);
    font-weight: 600;
  }
  .form-grid input {
    font: inherit;
    font-size: 13px;
    color: var(--ink);
    background: var(--panel);
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    padding: 7px 9px;
  }
  .form-grid input:focus { outline: none; border-color: var(--accent); }

  .search-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .search-go {
    align-self: flex-start;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    padding: 7px 14px;
    border-radius: 3px;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fdf6e8;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .search-go:hover:not(:disabled) { background: var(--accent-bright, #b03020); border-color: var(--accent-bright, #b03020); }
  .search-go:disabled { cursor: default; }
  /* Stay on-brand even while disabled — the inflight spinner already
     communicates the busy state; greyed-out doesn't add information. */
  .search-go.searching { opacity: 1; cursor: progress; }
  .search-cancel {
    font: inherit;
    font-size: 13px;
    padding: 7px 12px;
    border-radius: 3px;
    border: 1px solid var(--ink-12);
    background: var(--panel);
    color: var(--ink);
    cursor: pointer;
  }
  .search-cancel:hover { background: var(--ink-07); }
  .spinner {
    width: 11px;
    height: 11px;
    border: 2px solid rgba(253, 246, 232, 0.35);
    border-top-color: #fdf6e8;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: inline-block;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* mode tabs (CrossRef search ↔ Manual BibTeX) */
  .mode-tabs {
    display: inline-flex;
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 14px;
    align-self: flex-start;
  }
  .mode-tabs button {
    appearance: none;
    background: var(--panel);
    border: 0;
    padding: 5px 11px;
    font: inherit;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink-70);
    cursor: pointer;
  }
  .mode-tabs button.on { background: var(--ink); color: var(--backdrop, #fcfaf5); }
  .mode-tabs button:not(.on):hover { background: var(--panel-alt, #f6f1e6); }

  .manual-hint {
    margin-top: 12px;
    font-family: var(--serif);
    font-size: 12.5px;
    color: var(--ink-70);
  }
  .manual-hint .link {
    appearance: none;
    background: transparent;
    border: 0;
    padding: 0;
    color: var(--accent);
    font: inherit;
    font-size: inherit;
    cursor: pointer;
    text-decoration: underline;
  }
  .manual-prose {
    font-family: var(--serif);
    font-size: 13.5px;
    line-height: 1.45;
    color: var(--ink);
    margin: 0 0 12px;
  }
  .template-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 10px;
  }
  .template-row select {
    font: inherit;
    font-size: 13px;
    background: var(--panel);
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    padding: 6px 8px;
    color: var(--ink);
  }
  .template-hint {
    font-family: var(--serif);
    font-size: 12.5px;
    color: var(--ink-70);
    margin: 6px 0 12px;
    font-style: italic;
  }
  .bibtex-area {
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.5;
    background: var(--panel-alt, #f6f1e6);
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    padding: 10px 12px;
    width: 100%;
    resize: vertical;
    min-height: 240px;
    color: var(--ink);
    margin-bottom: 8px;
  }
  .bibtex-area:focus { outline: none; border-color: var(--accent); }

  .search-err {
    margin: 6px 0 0;
    font-family: var(--serif);
    font-size: 13px;
    color: var(--accent-bright, #b03020);
  }

  .candidates {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow: auto;
  }
  .cand {
    appearance: none;
    text-align: left;
    background: var(--panel);
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    padding: 7px 10px;
    cursor: pointer;
    width: 100%;
    transition: background 0.12s, border-color 0.12s;
  }
  .cand:hover:not(:disabled) {
    background: var(--panel-alt, #f6f1e6);
    border-color: var(--accent);
  }
  .cand.selected {
    background: var(--panel-alt, #f6f1e6);
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent) inset;
  }
  .cand.selected .cand-title { color: var(--accent); font-weight: 600; }
  .cand:disabled:not(.selected) { opacity: 0.55; cursor: default; }
  .commit-row {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--ink-12);
  }
  .commit-row .search-go { align-self: flex-start; }
  .commit-doi {
    font-size: 11.5px;
    background: rgba(255, 255, 255, 0.18);
    padding: 0 5px;
    border-radius: 2px;
    margin-left: 4px;
  }
  .cand-title {
    font-family: var(--serif);
    font-size: 13px;
    line-height: 1.25;
    color: var(--ink);
    margin-bottom: 2px;
  }
  .cand-meta {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: 11.5px;
    color: var(--ink-70);
    flex-wrap: wrap;
  }
  .cand-meta .dim { color: var(--ink-30); }
  .cand-meta .grow { flex: 1; }
  .cand-meta .doi {
    word-break: break-all;
    max-width: 60%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .cand-meta .score { font-size: 10.5px; }

  .ftr {
    padding: 12px 20px;
    border-top: 1px solid var(--ink-12);
    background: var(--backdrop);
    display: flex;
    justify-content: flex-end;
  }
  .ghost {
    appearance: none;
    background: transparent;
    border: 1px solid var(--ink-12);
    border-radius: 3px;
    padding: 6px 12px;
    font: inherit;
    font-size: 12.5px;
    color: var(--ink);
    cursor: pointer;
  }
  .ghost:hover { background: var(--ink-07); }

  .mono { font-family: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace; }
  .dim { color: var(--ink-30); }
  .caps {
    font-family: var(--sans);
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--ink-70);
    font-weight: 600;
  }
</style>

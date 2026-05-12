<!--
  InboxFindModal — replaces the old inline CrossRef-search form for an Inbox
  PDF with a side-by-side modal: the PDF rendered on the left (so the user can
  actually read the title block, byline, journal masthead), the existing
  search form + candidate list on the right.

  Reads/writes the same `searchByPath[pdfPath]` state used by the inline path,
  so opening the modal preserves whatever the user has already typed and
  closing it doesn't reset the candidates.

  The PDF preview is a minimal single-page render — page navigation, fit-width,
  no find / no annotations / no tab integration. That's deliberate: this is for
  identifying the paper, not for reading it.
-->
<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { TextLayer } from "pdfjs-dist";
  import { loadPdf, pdfUrlForPath, type PDFDocumentProxy } from "../lib/pdf";
  import {
    searchByPath,
    fileWithDoi,
    closeSearchFor,
    refreshInbox,
  } from "../state/inbox.svelte";
  import { toast } from "../state/toast.svelte";
  import { searchCrossref, inboxFileWithBibtex, inboxExtractBibtexStub, fetchCrossrefRecord, type FilingOutcome } from "../lib/vault";
  import { bibtexTemplates, findTemplate } from "../lib/bibtex-templates";

  type Props = {
    pdfPath: string;
    filename: string;
    onClose: () => void;
    onFiled?: (outcome: FilingOutcome) => void;
  };
  let { pdfPath, filename, onClose, onFiled }: Props = $props();

  /* Per-row state (title/author/year inputs + candidates). The inline
   * find path initialises this before opening the modal; we read/write
   * the same store so closing the modal preserves the user's work. */
  const search = $derived(searchByPath[pdfPath]);

  /* Two-way switch: CrossRef search (default) ↔ manual BibTeX entry. */
  let mode = $state<"search" | "manual">("search");

  /* Manual-entry state. */
  let templateType = $state(bibtexTemplates[0].type);
  let manualBibtex = $state(bibtexTemplates[0].template);
  let manualSubmitting = $state(false);
  let manualTouched = false;
  let autoFilling = $state(false);
  let autoFilledOnce = $state(false);
  function selectTemplate(type: string) {
    templateType = type;
    const t = findTemplate(type);
    if (!t) return;
    if (manualTouched && !window.confirm("Replace your edits with the selected template?")) return;
    manualBibtex = t.template;
    manualTouched = false;
    autoFilledOnce = false;
  }

  /* Pre-fill the BibTeX textarea from the PDF's own /Info + XMP +
   * first-page text. scripts/extract_pdf_meta.py does the heavy
   * lifting; we just inject the @misc{…} stub it returns. Falls back
   * to the static template if the script is missing or returns
   * nothing useful. */
  async function autoFillFromPdf() {
    if (autoFilling) return;
    if (manualTouched && !window.confirm("Replace your edits with the auto-filled stub from the PDF?")) return;
    autoFilling = true;
    try {
      const stub = await inboxExtractBibtexStub(pdfPath);
      if (stub) {
        manualBibtex = stub;
        manualTouched = false;
        autoFilledOnce = true;
        toast.info("Pre-filled from PDF metadata — review and edit before saving");
      } else {
        toast.error("Couldn't extract metadata from the PDF — vault may be missing extract_pdf_meta.py");
      }
    } catch (e) {
      toast.error(`Auto-fill failed: ${e}`);
    } finally {
      autoFilling = false;
    }
  }

  /* Auto-fill on the FIRST switch into manual mode (only once per
   * modal open; if the user resets to a template, they can hit the
   * button again). */
  $effect(() => {
    if (mode === "manual" && !autoFilledOnce && !manualTouched) {
      void autoFillFromPdf();
    }
  });
  async function submitManual() {
    if (manualSubmitting) return;
    manualSubmitting = true;
    try {
      const outcome = await inboxFileWithBibtex(pdfPath, manualBibtex);
      onFiled?.(outcome);
      switch (outcome.status) {
        case "filed":
          toast.info(`Filed as ${outcome.citekey ?? "?"}`);
          break;
        case "duplicate":
          toast.info(`Duplicate of ${outcome.citekey ?? "?"}`);
          break;
        default:
          toast.error(outcome.detail ?? outcome.status);
      }
      await refreshInbox();
      closeSearchFor(pdfPath);
      onClose();
    } catch (e) {
      toast.error(String(e));
    } finally {
      manualSubmitting = false;
    }
  }

  /* Per-candidate "Details" expander state. Keyed by DOI so re-runs
   * of the search don't lose what the user has open. Each entry is a
   * loading-or-loaded RECORD; the loaded form holds the raw JSON
   * string CrossRef returned (or DataCite, via the fallback). */
  type DetailsEntry =
    | { loading: true }
    | { loading: false; json: string; error: string | null };
  const detailsByDoi = $state<Record<string, DetailsEntry>>({});

  async function toggleDetails(doi: string): Promise<void> {
    if (detailsByDoi[doi]) {
      delete detailsByDoi[doi];
      return;
    }
    detailsByDoi[doi] = { loading: true };
    try {
      const raw = await fetchCrossrefRecord(doi);
      detailsByDoi[doi] = { loading: false, json: raw, error: null };
    } catch (e) {
      detailsByDoi[doi] = { loading: false, json: "", error: String(e) };
    }
  }

  /** Render the most useful fields from a CrossRef record as small
   *  key/value rows. Falls back to "—" for missing fields. */
  function summarizeRecord(raw: string): Array<{ k: string; v: string }> {
    if (!raw.trim()) return [];
    let msg: Record<string, unknown>;
    try { msg = JSON.parse(raw); } catch { return []; }
    const fmt = (x: unknown): string => {
      if (x == null) return "—";
      if (Array.isArray(x)) return x.map(fmt).join("; ");
      if (typeof x === "object") return JSON.stringify(x);
      return String(x);
    };
    const get = (k: string): string => fmt((msg as Record<string, unknown>)[k]);
    const authorsField = (msg as { author?: Array<{ family?: string; given?: string }> }).author ?? [];
    const authorsStr = authorsField
      .map((a) => [a.family, a.given].filter(Boolean).join(", "))
      .join("; ");
    const issued = (msg as { issued?: { "date-parts"?: number[][] } }).issued;
    const issuedYear = issued?.["date-parts"]?.[0]?.[0] ?? "";
    return [
      { k: "Type", v: get("type") },
      { k: "Title", v: ((msg as { title?: string[] }).title ?? []).join(" / ") || "—" },
      { k: "Authors", v: authorsStr || "—" },
      { k: "Journal", v: ((msg as { "container-title"?: string[] })["container-title"] ?? []).join(" / ") || "—" },
      { k: "Publisher", v: get("publisher") },
      { k: "Year", v: issuedYear ? String(issuedYear) : "—" },
      { k: "Volume", v: get("volume") },
      { k: "Issue", v: get("issue") },
      { k: "Pages", v: get("page") },
      { k: "DOI", v: get("DOI") },
      { k: "URL", v: get("URL") },
      { k: "ISSN", v: get("ISSN") },
      { k: "Subject", v: get("subject") },
      { k: "References", v: get("references-count") },
      { k: "Abstract", v: get("abstract") },
    ].filter((row) => row.v && row.v !== "—" && row.v !== "");
  }

  /* Cancellable CrossRef search — same pattern as ReidentifyModal:
   *   - each runSearch bumps a token, sets activeSearchToken
   *   - cancel = clear activeSearchToken → the in-flight result is ignored
   * The Rust command is async (spawn_blocking), so canceling here doesn't
   * actually stop the running subprocess but does free the UI immediately. */
  let activeSearchToken = $state<number | null>(null);
  let searchToken = 0;
  let searching = $derived(activeSearchToken !== null);

  /* Click-to-select; separate File button commits — avoids misclicks
   * committing a wrong CrossRef record. */
  let selectedDoi = $state<string | null>(null);
  let selectedCand = $derived(
    selectedDoi && search
      ? search.candidates.find((c) => c.doi === selectedDoi) ?? null
      : null,
  );
  let busyFiling = $state(false);
  async function commitSelected() {
    if (!selectedDoi || busyFiling) return;
    busyFiling = true;
    try {
      await pickCandidate(selectedDoi);
    } finally {
      busyFiling = false;
    }
  }
  async function runSearch() {
    if (!search) return;
    if (searching) return;
    const myToken = ++searchToken;
    activeSearchToken = myToken;
    search.error = null;
    try {
      const y = search.year.trim() ? parseInt(search.year.trim(), 10) : undefined;
      if (y !== undefined && Number.isNaN(y)) {
        if (activeSearchToken === myToken) search.error = "Year must be a number";
        return;
      }
      const result = await searchCrossref({
        title: search.title || undefined,
        author: search.author || undefined,
        query: search.query || undefined,
        year: y,
      });
      if (activeSearchToken !== myToken) return;
      search.candidates = result;
      if (result.length === 0) search.error = "No matches from CrossRef";
    } catch (e) {
      if (activeSearchToken !== myToken) return;
      search.error = String(e);
      search.candidates = [];
    } finally {
      if (activeSearchToken === myToken) activeSearchToken = null;
    }
  }
  function cancelSearch() {
    activeSearchToken = null;
  }

  /* --- PDF rendering --- */
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

  /* Render the current page whenever doc, pageNum, or the wrapper width changes.
   * `renderToken` lets us abort stale renders when the user pages quickly. */
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
        /* Selectable text overlay — same pattern as PDFView / ReidentifyModal. */
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

  /* --- actions --- */
  function setPage(n: number) {
    if (!doc) return;
    pageNum = Math.max(1, Math.min(doc.numPages, n));
  }

  /* Search button → runSearch (the cancellable local impl above). */

  async function pickCandidate(doi: string) {
    try {
      const outcome = await fileWithDoi(pdfPath, doi);
      onFiled?.(outcome);
      switch (outcome.status) {
        case "filed":
          toast.info(`Filed as ${outcome.citekey ?? "?"}`);
          break;
        case "duplicate":
          toast.info(`Duplicate of ${outcome.citekey ?? "?"}`);
          break;
        default:
          toast.error(outcome.detail ?? outcome.status);
      }
      onClose();
    } catch (e) {
      toast.error(String(e));
    }
  }

  function cancel() {
    closeSearchFor(pdfPath);
    onClose();
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
    aria-label="Identify this PDF"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="hdr">
      <div class="hdr-left">
        <p class="caps">Identify · no DOI found in PDF</p>
        <p class="filename mono" title={pdfPath}>{filename}</p>
      </div>
      <button class="close" onclick={cancel} aria-label="Close">×</button>
    </header>

    <div class="body">
      <!-- Left: PDF preview -->
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

      <!-- Right: CrossRef search + candidates -->
      <section class="form-side">
        <div class="mode-tabs" role="tablist">
          <button
            class:on={mode === "search"}
            onclick={() => (mode = "search")}
            role="tab"
            aria-selected={mode === "search"}
          >CrossRef search</button>
          <button
            class:on={mode === "manual"}
            onclick={() => (mode = "manual")}
            role="tab"
            aria-selected={mode === "manual"}
          >Manual BibTeX</button>
        </div>

        {#if mode === "search"}
          {#if search}
            <p class="caps form-eyebrow">Search hints</p>
            <div class="form-grid">
              <label>
                <span class="caps-label">Title</span>
                <input
                  type="text"
                  bind:value={search.title}
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
                  bind:value={search.author}
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
                  bind:value={search.year}
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

            {#if search.error}
              <p class="search-err">{search.error}</p>
            {/if}

            {#if search.candidates.length > 0}
              <p class="caps form-eyebrow candidates-hdr">Candidates ({search.candidates.length})</p>
              <ul class="candidates">
                {#each search.candidates as c, ci (c.doi ?? `none-${ci}`)}
                  {@const det = c.doi ? detailsByDoi[c.doi] : undefined}
                  <li>
                    <div class="cand-row">
                      <button
                        class="cand"
                        class:selected={c.doi && selectedDoi === c.doi}
                        disabled={!c.doi}
                        onclick={() => c.doi && (selectedDoi = c.doi)}
                        title={c.doi ? "Select; click File below to commit" : "Candidate has no DOI"}
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
                      {#if c.doi}
                        <button
                          class="cand-details-btn"
                          class:open={!!det}
                          onclick={() => toggleDetails(c.doi!)}
                          title={det ? "Hide CrossRef record" : "Fetch full CrossRef record for this candidate"}>
                          {det && !det.loading ? "▾ details" : "▸ details"}
                        </button>
                      {/if}
                    </div>
                    {#if det}
                      <div class="cand-details">
                        {#if det.loading}
                          <div class="cand-details-loading">Loading CrossRef record…</div>
                        {:else if det.error}
                          <div class="cand-details-error">Couldn't load: {det.error}</div>
                        {:else}
                          {@const rows = summarizeRecord(det.json)}
                          {#if rows.length > 0}
                            <dl class="cand-details-dl">
                              {#each rows as r (r.k)}
                                <dt>{r.k}</dt>
                                <dd>{r.v}</dd>
                              {/each}
                            </dl>
                          {/if}
                          <details class="cand-details-raw">
                            <summary>raw JSON</summary>
                            <pre>{det.json}</pre>
                          </details>
                        {/if}
                      </div>
                    {/if}
                  </li>
                {/each}
              </ul>

              <div class="commit-row">
                <button
                  class="search-go"
                  disabled={!selectedDoi || busyFiling}
                  onclick={commitSelected}
                  title={selectedDoi ? `File with DOI ${selectedDoi}` : "Select a candidate above first"}
                >
                  {#if busyFiling}
                    <span class="spinner" aria-hidden="true"></span>
                    Filing…
                  {:else if selectedCand}
                    File as <span class="commit-doi mono">{selectedCand.doi}</span>
                  {:else}
                    File (select a candidate)
                  {/if}
                </button>
              </div>
            {/if}

            <p class="manual-hint">
              Not in CrossRef? Switch to <button
                class="link"
                onclick={() => (mode = "manual")}>Manual BibTeX</button>.
            </p>
          {:else}
            <p class="empty">No search state — close and re-open Find on the row.</p>
          {/if}
        {:else}
          <p class="caps form-eyebrow">Enter the BibTeX entry directly</p>
          <p class="manual-prose">
            For books, theses, preprints without DOIs, web pages, and anything
            else CrossRef doesn't have. Pick a template, fill the placeholders,
            and the entry will become this paper's <span class="mono">.bib</span>
            on disk.
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
            <button
              class="auto-fill-btn"
              disabled={autoFilling}
              onclick={autoFillFromPdf}
              title="Re-read the PDF's metadata and replace this BibTeX with a fresh stub">
              {autoFilling ? "Reading…" : "Auto-fill from PDF"}
            </button>
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
      <button class="ghost" onclick={cancel}>Cancel · keep in Inbox</button>
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
    gap: 0;
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
    line-height: 1;
    color: var(--accent);
    padding: 2px 6px;
    border-radius: 3px;
  }
  .page-nav button:hover:not(:disabled) { background: var(--ink-07); }
  .page-nav button:disabled { color: var(--ink-30); cursor: default; }
  .page-num {
    font-size: 12px;
    color: var(--ink-70);
  }

  .form-side {
    padding: 18px 22px;
    overflow: auto;
    display: flex;
    flex-direction: column;
  }
  .form-eyebrow {
    color: var(--accent);
    margin: 0 0 10px;
  }
  .candidates-hdr { margin-top: 18px; }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 12px;
    margin-bottom: 12px;
  }
  .form-grid label:first-child { grid-column: 1 / -1; }
  .form-grid label {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
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
  .form-grid input:focus {
    outline: none;
    border-color: var(--accent);
  }

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
    display: grid;
    grid-template-columns: 1fr auto;
    column-gap: 10px;
    row-gap: 4px;
    align-items: end;
    margin-bottom: 10px;
  }
  .template-row .caps-label {
    grid-column: 1 / -1;
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
  /* "Auto-fill from PDF" sits next to the template picker. Editorial
     hairline-outline button; flips to the accent color on hover. */
  .auto-fill-btn {
    border: 1px solid var(--accent);
    background: transparent;
    color: var(--accent);
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 6px 12px;
    border-radius: 0;
    cursor: pointer;
    white-space: nowrap;
  }
  .auto-fill-btn:hover:not(:disabled) {
    background: var(--accent);
    color: var(--panel);
  }
  .auto-fill-btn:disabled {
    opacity: 0.5;
    cursor: wait;
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
  .empty {
    color: var(--ink-50);
    font-size: 13px;
    font-style: italic;
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
  /* Candidate row: select-button on the left (flex-grows to the row
     width), tiny details-toggle on the right. The toggle sits in the
     same row so it shares the candidate's visual scope. */
  .cand-row {
    display: flex;
    align-items: stretch;
    gap: 4px;
  }
  .cand-details-btn {
    appearance: none;
    flex-shrink: 0;
    border: 1px solid var(--ink-12);
    background: transparent;
    color: var(--ink-50);
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 0 10px;
    cursor: pointer;
    border-radius: 4px;
    white-space: nowrap;
  }
  .cand-details-btn:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .cand-details-btn.open {
    color: var(--accent);
    border-color: var(--accent);
  }
  /* Expanded details panel — under the candidate row, faint accent
     left rule so the relationship is unambiguous. */
  .cand-details {
    border-left: 2px solid var(--accent);
    background: var(--panel-alt, #f6f1e6);
    padding: 10px 12px;
    margin: 0 0 6px 4px;
    font-family: var(--sans);
    font-size: 12px;
  }
  .cand-details-loading,
  .cand-details-error {
    font-style: italic;
    color: var(--ink-70);
  }
  .cand-details-error { color: var(--accent); }
  .cand-details-dl {
    display: grid;
    grid-template-columns: 110px 1fr;
    column-gap: 12px;
    row-gap: 2px;
    margin: 0;
  }
  .cand-details-dl dt {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--ink-50);
    padding-top: 1px;
  }
  .cand-details-dl dd {
    margin: 0;
    color: var(--ink);
    word-break: break-word;
  }
  .cand-details-raw {
    margin-top: 8px;
    font-family: var(--mono);
    font-size: 10.5px;
  }
  .cand-details-raw summary {
    cursor: pointer;
    color: var(--ink-50);
    letter-spacing: 0.4px;
  }
  .cand-details-raw pre {
    max-height: 240px;
    overflow: auto;
    background: var(--panel);
    border: 1px solid var(--ink-12);
    padding: 8px;
    margin: 6px 0 0;
    border-radius: 3px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .cand {
    flex: 1;
    appearance: none;
    text-align: left;
    background: var(--panel);
    border: 1px solid var(--ink-12);
    border-radius: 4px;
    padding: 9px 11px;
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
    font-size: 13.5px;
    line-height: 1.3;
    color: var(--ink);
    margin-bottom: 4px;
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

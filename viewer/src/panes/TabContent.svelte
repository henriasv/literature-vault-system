<script lang="ts">
  import { PaneGroup, Pane, PaneResizer } from "paneforge";
  import { tabsState, openInTab } from "../state/tabs.svelte";
  import { prefsState } from "../state/prefs.svelte";
  import { libraryState } from "../state/library.svelte";
  import { paperLabel, paperSubline, type PaperMeta } from "../lib/vault";
  import NoteEditor from "./NoteEditor.svelte";
  import PDFView from "./PDFView.svelte";
  import EmbedPDFView from "./EmbedPDFView.svelte";

  /* Feature flag — flip in DevTools console with
   *   localStorage.setItem('vault.embedPdf', '1'); location.reload();
   * and back with
   *   localStorage.removeItem('vault.embedPdf'); location.reload();
   * to compare the EmbedPDF spike against the existing hand-rolled
   * PDFView. Lives in localStorage rather than settings so it's per-window
   * and trivially togglable. */
  const useEmbedPdf =
    typeof localStorage !== "undefined" &&
    localStorage.getItem("vault.embedPdf") === "1";

  const initialPdfPct = $derived(Math.round(prefsState.splitRatio * 100));

  const recentPapers = $derived.by<PaperMeta[]>(() => {
    const order = new Map(prefsState.recents.map((r, i) => [r.citekey, i]));
    return libraryState.papers
      .filter((p) => order.has(p.citekey))
      .sort((a, b) => order.get(a.citekey)! - order.get(b.citekey)!)
      .slice(0, 10);
  });

  function onLayoutChange(layout: number[]) {
    if (!Array.isArray(layout) || layout.length === 0) return;
    const pdf = layout[0];
    if (Number.isFinite(pdf)) {
      const ratio = pdf / 100;
      if (Math.abs(ratio - prefsState.splitRatio) > 0.001) {
        prefsState.splitRatio = ratio;
      }
    }
  }
</script>

<div class="tab-stack">
  {#if tabsState.tabs.length === 0}
    <div class="empty">
      <h2>Recently opened</h2>
      {#if recentPapers.length === 0}
        <p class="hint">⌘T to focus the library search · ⌘N to add a paper</p>
      {:else}
        <ul>
          {#each recentPapers as p (p.citekey)}
            <li>
              <button onclick={() => openInTab(p.citekey)}>
                <div class="title">{p.title}</div>
                <div class="sub">{paperLabel(p)} · {paperSubline(p)}</div>
              </button>
            </li>
          {/each}
        </ul>
        <p class="hint">⌘T to search · ⌘N to add a paper</p>
      {/if}
    </div>
  {:else}
    {#each tabsState.tabs as tab, i (tab.citekey)}
      <div class="tab-pane" class:active={i === tabsState.activeIndex}>
        <PaneGroup direction="horizontal" {onLayoutChange}>
          <Pane defaultSize={initialPdfPct} minSize={20} maxSize={80}>
            {#if useEmbedPdf}
              <EmbedPDFView citekey={tab.citekey} />
            {:else}
              <PDFView citekey={tab.citekey} page={tab.pdfPage} zoom={tab.pdfZoom} />
            {/if}
          </Pane>
          <PaneResizer class="splitter" />
          <Pane defaultSize={100 - initialPdfPct} minSize={20} maxSize={80}>
            <NoteEditor citekey={tab.citekey} />
          </Pane>
        </PaneGroup>
      </div>
    {/each}
  {/if}
</div>

<style>
  .tab-stack {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .tab-pane {
    position: absolute;
    inset: 0;
    visibility: hidden;
  }
  .tab-pane.active {
    visibility: visible;
  }
  .tab-pane :global([data-pane-group]) {
    height: 100%;
  }
  .tab-pane :global(.splitter) {
    width: 4px;
    background: var(--border);
    cursor: col-resize;
    position: relative;
  }
  .tab-pane :global(.splitter:hover) {
    background: var(--accent);
  }
  .tab-pane :global([data-pane]) {
    overflow: hidden;
    min-width: 0;
  }
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 32px;
    color: var(--muted);
  }
  .empty h2 {
    margin: 0;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .empty ul {
    list-style: none;
    padding: 0;
    margin: 0;
    width: min(100%, 480px);
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
  }
  .empty li {
    border-bottom: 1px solid var(--border);
  }
  .empty li:last-child {
    border-bottom: 0;
  }
  .empty li button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 8px 12px;
    cursor: pointer;
    border-radius: 0;
    color: var(--fg);
  }
  .empty li button:hover {
    background: var(--hover);
  }
  .empty .title {
    font-size: 12px;
    line-height: 1.3;
    margin-bottom: 2px;
  }
  .empty .sub {
    color: var(--muted);
    font-size: 11px;
  }
  .hint {
    font-size: 11px;
    margin: 0;
  }
</style>

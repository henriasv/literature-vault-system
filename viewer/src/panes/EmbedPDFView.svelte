<!--
  EmbedPDFView — headless EmbedPDF integration with our own toolbar.

  Plugins wired (minimum for read + select + highlight):
    viewport · scroll · document-manager · interaction-manager
    · render · tiling · zoom · selection · search · annotation · history

  Deliberately omitted: pan, spread, rotate, print, export, redaction,
  signature, stamp, form, fullscreen, capture, ai, i18n, layout-analysis,
  thumbnail, embedpdf's own UI plugin. See the trade-off discussion.

  Per-tab persistence (session.json sync) and the floating annotation
  toolbar / sidecar JSON come in the next turns.
-->
<script lang="ts">
  import { EmbedPDF } from "@embedpdf/core/svelte";
  import { usePdfiumEngine } from "@embedpdf/engines/svelte";
  import { createPluginRegistration, type PluginRegistry } from "@embedpdf/core";
  import { ConsoleLogger } from "@embedpdf/models";

  import { ViewportPluginPackage, Viewport } from "@embedpdf/plugin-viewport/svelte";
  import {
    ScrollPluginPackage,
    ScrollStrategy,
    Scroller,
  } from "@embedpdf/plugin-scroll/svelte";
  import {
    DocumentManagerPluginPackage,
    DocumentContent,
    DocumentManagerPlugin,
  } from "@embedpdf/plugin-document-manager/svelte";
  import {
    InteractionManagerPluginPackage,
    GlobalPointerProvider,
    PagePointerProvider,
  } from "@embedpdf/plugin-interaction-manager/svelte";
  import { ZoomMode, ZoomPluginPackage, ZoomGestureWrapper } from "@embedpdf/plugin-zoom/svelte";
  import { RenderLayer, RenderPluginPackage } from "@embedpdf/plugin-render/svelte";
  import { TilingLayer, TilingPluginPackage } from "@embedpdf/plugin-tiling/svelte";
  import { SelectionLayer, SelectionPluginPackage } from "@embedpdf/plugin-selection/svelte";
  import { SearchLayer, SearchPluginPackage } from "@embedpdf/plugin-search/svelte";
  import {
    AnnotationPluginPackage,
    AnnotationPlugin,
    RendererRegistryProvider,
  } from "@embedpdf/plugin-annotation/svelte";
  import { HistoryPluginPackage } from "@embedpdf/plugin-history/svelte";

  import EmbedPdfToolbar from "./EmbedPdfToolbar.svelte";
  import EmbedHighlightSelectionMenu from "./EmbedHighlightSelectionMenu.svelte";
  import EmbedPageAnnotations from "./EmbedPageAnnotations.svelte";
  import EmbedAnnotationKeybinds from "./EmbedAnnotationKeybinds.svelte";
  import { pdfUrlFor } from "../lib/pdf";
  import { readAnnotations, writeAnnotations } from "../lib/vault";
  import { HIGHLIGHT_COLORS } from "../lib/highlight-colors";

  type Props = { citekey: string };
  let { citekey }: Props = $props();

  const logger = new ConsoleLogger();
  const pdfEngine = usePdfiumEngine({ logger });

  const plugins = [
    createPluginRegistration(ViewportPluginPackage, { viewportGap: 10 }),
    createPluginRegistration(ScrollPluginPackage, {
      defaultStrategy: ScrollStrategy.Vertical,
    }),
    createPluginRegistration(DocumentManagerPluginPackage),
    createPluginRegistration(InteractionManagerPluginPackage),
    createPluginRegistration(ZoomPluginPackage, {
      defaultZoomLevel: ZoomMode.FitPage,
    }),
    createPluginRegistration(RenderPluginPackage),
    createPluginRegistration(TilingPluginPackage, {
      tileSize: 768,
      overlapPx: 2.5,
      extraRings: 0,
    }),
    createPluginRegistration(SelectionPluginPackage),
    createPluginRegistration(SearchPluginPackage),
    createPluginRegistration(AnnotationPluginPackage, {
      annotationAuthor: "Literature Vault",
      autoCommit: true,
      /* Color presets — surfaced by EmbedPDF in any plugin-rendered UI it
       * shows. Our toolbar uses these same four; the array is the source of
       * truth so picking/configuring colors only happens here. */
      colorPresets: HIGHLIGHT_COLORS,
    }),
    createPluginRegistration(HistoryPluginPackage),
  ];

  let pdfSrc = $state<string | null>(null);
  let srcError = $state<string | null>(null);

  /* `.ep-host` ref + capture-phase wheel clamp.
   *
   * macOS trackpads (and to a lesser extent ⌘+wheel on a mouse)
   * deliver an unusually large deltaY in the first wheel event of a
   * pinch gesture — often 30–60 px instead of the 1–3 of follow-up
   * events. EmbedPDF's wheel handler converts each delta into
   * `scale *= 1 - deltaY*0.01`, so a single 50-px first frame jumps
   * the in-flight scale to ~0.5 and the transform's translate
   * (`pointerLocalY * (1 - scale)`) becomes huge when the cursor is
   * deep into a long document. The plugin then commits the
   * accumulated zoom + reverts the transform on gesture end, and
   * the round-trip looks like a "jump out, then jump back" that the
   * user sees framing each pinch.
   *
   * Fix: intercept wheel events at the .ep-host (capture phase, non-
   * passive) and, when a ctrl/meta-modified event arrives with
   * |deltaY| > MAX_DELTA, replay it as a clamped synthetic event.
   * The plugin's bubble-phase listener on the inner container sees a
   * sane delta, scales smoothly, and start/end jumps disappear. */
  let epHost = $state<HTMLDivElement | null>(null);

  $effect(() => {
    const host = epHost;
    if (!host) return;
    const MAX_DELTA = 8;
    let inDispatch = false;

    function onCaptureWheel(e: WheelEvent) {
      if (inDispatch) return;
      if (!e.ctrlKey && !e.metaKey) return;
      if (Math.abs(e.deltaY) <= MAX_DELTA) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      const sign = Math.sign(e.deltaY) || 1;
      const clamped = new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        composed: true,
        view: window,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        shiftKey: e.shiftKey,
        altKey: e.altKey,
        deltaX: 0,
        deltaY: sign * MAX_DELTA,
        deltaZ: 0,
        deltaMode: e.deltaMode,
        clientX: e.clientX,
        clientY: e.clientY,
        screenX: e.screenX,
        screenY: e.screenY,
      });
      inDispatch = true;
      try {
        (e.target as EventTarget | null)?.dispatchEvent(clamped);
      } finally {
        inDispatch = false;
      }
    }

    host.addEventListener("wheel", onCaptureWheel, {
      capture: true,
      passive: false,
    });
    return () => {
      host.removeEventListener("wheel", onCaptureWheel, { capture: true });
    };
  });

  /* Resolve citekey → asset:// URL the engine can fetch. */
  $effect(() => {
    const ck = citekey;
    pdfSrc = null;
    srcError = null;
    void (async () => {
      try {
        pdfSrc = await pdfUrlFor(ck);
      } catch (e) {
        srcError = String(e);
      }
    })();
  });

  /* When the registry is ready we open the PDF and wire up sidecar persistence.
   * Sidecar format is EmbedPDF's native `AnnotationTransferItem[]` JSON,
   * stored at `Annotations/{citekey}.json`. We persist *only* user-added
   * highlights — never the annotations already embedded in the PDF file.
   *
   * The trick: PDFs in our vault often arrive with hundreds of embedded
   * annotations (e.g. publisher links). EmbedPDF reads them on load and
   * fires a `create` event for each, then one `loaded` event when done.
   * We treat that loaded snapshot as the "baseline" and exclude those IDs
   * from every export. Anything imported from our sidecar afterwards, or
   * created via the selection menu, falls outside the baseline and gets
   * round-tripped to disk.
   *
   * XFDF conversion only happens at export-PDF time (when we want to share
   * annotations with other readers); the in-app sidecar stays JSON. */
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  async function onInitialized(registry: PluginRegistry) {
    if (!pdfSrc) return;
    const dm = registry.getPlugin<DocumentManagerPlugin>(DocumentManagerPlugin.id);
    const ann = registry.getPlugin<AnnotationPlugin>(AnnotationPlugin.id);
    const provides = ann?.provides();
    if (!provides) {
      console.warn("[EmbedPDF] annotation capability missing — sidecar persistence disabled");
      await dm?.provides()?.openDocumentUrl({ url: pdfSrc }).toPromise();
      return;
    }

    let baseline: Set<string> | null = null;
    const scheduleSave = () => {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        saveTimer = null;
        if (!baseline) return;
        try {
          const items = (await provides.exportAnnotations({}).toPromise()) ?? [];
          const userOnly = items.filter((it) => !baseline!.has(it.annotation.id));
          await writeAnnotations(citekey, JSON.stringify(userOnly));
        } catch (e) {
          console.warn("[EmbedPDF] failed to save annotation sidecar", e);
        }
      }, 600);
    };

    const off = provides.onAnnotationEvent((evt) => {
      if (evt.type === "loaded") {
        /* Initial PDF-embedded annotations have been ingested. Snapshot
         * their IDs as the baseline, then layer our sidecar on top. */
        const current = provides.getAnnotations();
        baseline = new Set(current.map((t) => t.object.id));
        void (async () => {
          try {
            const raw = await readAnnotations(citekey);
            if (raw && raw.trim().length > 0) {
              const items = JSON.parse(raw);
              if (Array.isArray(items) && items.length > 0) {
                provides.importAnnotations(items);
              }
            }
          } catch (e) {
            console.warn("[EmbedPDF] failed to load annotation sidecar", e);
          }
        })();
        return;
      }
      if (!baseline) return; // ignore creates fired before the loaded snapshot
      scheduleSave();
    });

    await dm?.provides()?.openDocumentUrl({ url: pdfSrc }).toPromise();
    /* TODO: when the doc is closed (tab switch / vault swap), unsubscribe
     * via `off?.()`. The current spike unmounts EmbedPDFView entirely on
     * those events so the listener is GC'd; revisit when multiple docs
     * share one EmbedPDF instance. */
    void off;
  }
</script>

<div class="ep-host" bind:this={epHost}>
  {#if pdfEngine.error}
    <div class="banner err">PDF engine failed: {pdfEngine.error.message}</div>
  {:else if srcError}
    <div class="banner err">PDF not found: {srcError}</div>
  {:else if pdfEngine.isLoading || !pdfEngine.engine || !pdfSrc}
    <div class="banner muted">Loading…</div>
  {:else}
    <EmbedPDF engine={pdfEngine.engine} {logger} {plugins} {onInitialized}>
      {#snippet children({ pluginsReady, activeDocumentId })}
        {#if !pluginsReady}
          <div class="banner muted">Initializing…</div>
        {:else if !activeDocumentId}
          <div class="banner muted">Loading document…</div>
        {:else}
          <EmbedPdfToolbar documentId={activeDocumentId} />

          <DocumentContent documentId={activeDocumentId}>
            {#snippet children({ isLoading, isError, isLoaded })}
              {#if isLoading}
                <div class="banner muted">Loading document…</div>
              {:else if isError}
                <div class="banner err">Failed to load document.</div>
              {:else if isLoaded}
                <div class="doc-area">
                  <!-- RendererRegistryProvider must wrap any <Annotations>
                       instance — it stores the per-type renderer map (Highlight,
                       Underline, …) that <Annotations> reads from. -->
                  <RendererRegistryProvider>
                    <EmbedAnnotationKeybinds />
                    <GlobalPointerProvider documentId={activeDocumentId}>
                      <Viewport class="ep-viewport" documentId={activeDocumentId}>
                        <ZoomGestureWrapper documentId={activeDocumentId}>
                        <Scroller documentId={activeDocumentId}>
                          {#snippet renderPage(page)}
                            <div class="page-bg" style:width="{page.width}px" style:height="{page.height}px">
                              <PagePointerProvider
                                documentId={activeDocumentId}
                                pageIndex={page.pageIndex}
                              >
                                <RenderLayer
                                  documentId={activeDocumentId}
                                  pageIndex={page.pageIndex}
                                  scale={1}
                                  style="pointer-events: none"
                                />
                                <TilingLayer
                                  documentId={activeDocumentId}
                                  pageIndex={page.pageIndex}
                                  style="pointer-events: none"
                                />
                                <SearchLayer
                                  documentId={activeDocumentId}
                                  pageIndex={page.pageIndex}
                                />
                                <!-- Renders highlights from state.byUid so they
                                     re-appear on reload, and shows handles when
                                     an existing annotation is selected. The
                                     wrapper pulls scale from useZoom because
                                     the Scroller's snippet param doesn't expose
                                     it — passing scale=1 leaves overlays
                                     drifted at any zoom != 100%. The
                                     text-selection menu (for creating new
                                     highlights) stays on SelectionLayer
                                     below. -->
                                <EmbedPageAnnotations
                                  documentId={activeDocumentId}
                                  pageIndex={page.pageIndex}
                                  pageWidth={page.width}
                                  pageHeight={page.height}
                                />
                                <SelectionLayer
                                  documentId={activeDocumentId}
                                  pageIndex={page.pageIndex}
                                >
                                  {#snippet selectionMenuSnippet(props)}
                                    <EmbedHighlightSelectionMenu
                                      documentId={activeDocumentId}
                                      {citekey}
                                      {...props}
                                    />
                                  {/snippet}
                                </SelectionLayer>
                              </PagePointerProvider>
                            </div>
                          {/snippet}
                        </Scroller>
                        </ZoomGestureWrapper>
                      </Viewport>
                    </GlobalPointerProvider>
                  </RendererRegistryProvider>
                </div>
              {/if}
            {/snippet}
          </DocumentContent>
        {/if}
      {/snippet}
    </EmbedPDF>
  {/if}
</div>

<style>
  .ep-host {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--backdrop, #fcfaf5);
  }
  .doc-area {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
  }
  .ep-host :global(.ep-viewport) {
    background: var(--recess, #e6dfc8);
    width: 100%;
    height: 100%;
  }
  .page-bg {
    background: white;
    box-shadow: 0 2px 8px -2px rgba(26, 22, 18, 0.18);
    position: relative;
  }
  .banner {
    padding: 20px;
    text-align: center;
    font-size: 13px;
  }
  .banner.muted { color: var(--ink-50, rgba(0, 0, 0, 0.5)); }
  .banner.err { color: #b03020; }
</style>

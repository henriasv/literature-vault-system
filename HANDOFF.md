# Handoff — EmbedPDF annotation pipeline

Context for whoever picks up the Viewer next. This is the stuff you can't
derive from reading the code, plus the open follow-ups.

## What's working as of this handoff

- **PDF reader**: `viewer/src/panes/EmbedPDFView.svelte` is the new EmbedPDF-based
  reader. The legacy pdfjs-based `PDFView.svelte` is still in tree behind a
  feature flag in `TabContent.svelte`:
  `localStorage.setItem('vault.embedPdf', '1')` to use the new one.
- **Highlights** — multi-color (4 swatches in `lib/highlight-colors.ts`), drawn
  via a custom selection menu on text-select, persisted to a JSON sidecar at
  `<vault>/Annotations/<citekey>.json`.
- **Delete**: click a highlight → small menu with Delete button.
  Backspace/Delete keyboard shortcut works too (skipped inside inputs).

## Non-obvious bits of the EmbedPDF wiring

These took some figuring out — don't lose them.

### 1. `<Annotations>` needs `<RendererRegistryProvider>` above it

The provider's Svelte context carries the built-in renderers (Highlight,
Underline, FreeText, …). Without the provider, the overlay component mounts
but renders nothing. See `EmbedPDFView.svelte` — the provider wraps the
whole `<Viewport>`/`<Scroller>` tree.

### 2. `<Annotations>` scale comes from `useZoom`, not `page.scale`

The Scroller's `renderPage` snippet hands you a `PageLayout` (pageNumber,
pageIndex, width, height, rotatedWidth, …) — no `scale`/`rotation`. The
Svelte `.d.ts` for `RenderPageProps` includes them but the runtime snippet
doesn't pass them. If you set `<Annotations scale={1} …>` the overlays
drift relative to the underlying text at any zoom other than 100%.

Fix: `EmbedPageAnnotations.svelte` is a thin per-page wrapper that calls
`useZoom(() => documentId)` and feeds the live `currentZoomLevel` into
`<Annotations scale={…}>`. `useZoom` only works from inside the EmbedPDF
plugin tree, which is why it's a child component instead of a top-level
read.

### 3. PDFium tile renders intentionally exclude annotations

PDFium worker renders use `withAnnotations: false` — visible highlights
come **only** from our overlay. `autoCommit: true` writes annotations into
the in-memory PDF (so they round-trip cleanly into XFDF later) but the
tile renderer ignores them.

This means if `<Annotations>` ever stops mounting, all highlights vanish
visually even though the data is intact in `state.byUid`.

### 4. Sidecar format and the baseline trick

`<vault>/Annotations/<citekey>.json` is EmbedPDF's native
`AnnotationTransferItem[]` JSON, written verbatim. XFDF conversion is
deferred to export time (the future `scripts/export_paper.py`).

**Baseline filter** (the part that's easy to break): a PDF may already
contain embedded annotations (one test paper had 3,321 — publisher links,
prior reader highlights, etc.). On the `loaded` event we snapshot all
annotation IDs as the "baseline", then `importAnnotations` from the
sidecar. On every save we filter the export to exclude baseline IDs, so
the sidecar only ever contains the user's own highlights.

Without this filter, the sidecar grows to multi-megabyte JSON full of the
PDF's pre-existing annotations.

### 5. Two separate selection-menu snippets

There are two unrelated "selection menus" in EmbedPDF, and we wire both:

| Layer            | Triggered by         | Our component                       | Purpose            |
|------------------|----------------------|-------------------------------------|--------------------|
| `SelectionLayer` | text selection       | `EmbedHighlightSelectionMenu.svelte`| Create highlights  |
| `<Annotations>`  | annotation selection | `EmbedAnnotationSelectionMenu.svelte`| Delete/edit existing |

Don't conflate them — they take different `context` types
(`SelectionContext` vs `AnnotationSelectionContext`).

### 6. Vite HMR gotcha when adding `.svelte` files

When you create a new `.svelte` file (especially under `panes/`), Vite's
HMR sometimes won't pick it up — the component imports fine to TS but
just doesn't mount at runtime. **Hard reload** (Cmd+Shift+R) or restart
`npm run tauri dev`. We lost a debugging cycle to this; add an obvious
debug border like `border: 2px dashed red` if you're unsure a new
component is mounting.

## Open follow-ups

Roughly in order of "biggest user-visible gap first":

- **PDFium memory leak** — `PDFiumEngine.MemoryManager` logs "Potential
  memory leak: 1 unfreed allocations" of ~50 MB on every document close
  (`openDocumentBuffer` allocation that isn't paired with a free).
  Hasn't bitten us yet but flipping through many tabs in one session
  will eventually eat RAM. Probably an EmbedPDF-side issue — worth a
  GitHub issue upstream before patching locally.
- **Per-tab scroll/zoom/page state isn't persisted.** `session.svelte.ts`
  used to forward this for the pdfjs `PDFView`; nothing wired for
  EmbedPDF yet. Use `useZoom` and `useScroll` capabilities and emit
  setter calls in an `onmount`/`$effect`.
- **Export pipeline** (`scripts/export_paper.py`) — flatten the sidecar's
  JSON into XFDF, splat it into the PDF via PDFium, then append the
  rendered Markdown note. Spec: see `docs/DESIGN.md` (export section).
- **Standalone PDF intake fallback** — spec exists at
  `docs/fallback_intake_spec.md` (was in the librarian_assistant_vault
  repo originally — check whether it was copied over). Not started.
- **Rotation support** — `EmbedPageAnnotations` hardcodes `rotation={0}`.
  Wire `page.rotation` from the same path as scale when you hit a
  rotated PDF.

## Where things live

- **Viewer code**: `viewer/src/panes/`
  - `EmbedPDFView.svelte` — host; opens the doc, wires the annotation
    sidecar (load + debounced save with baseline filter), mounts plugins.
  - `EmbedPdfToolbar.svelte` — page nav, zoom, find, annotate-mode toggle.
  - `EmbedPageAnnotations.svelte` — per-page `<Annotations>` wrapper that
    pulls scale from `useZoom`.
  - `EmbedHighlightSelectionMenu.svelte` — color picker on text-select.
  - `EmbedAnnotationSelectionMenu.svelte` — Delete button on annotation-select.
  - `EmbedAnnotationKeybinds.svelte` — global Delete/Backspace listener.
- **Rust backend** for sidecar I/O: `viewer/src-tauri/src/vault.rs` —
  `read_annotations` / `write_annotations` commands.
- **Vault data model & embed server**: `docs/DESIGN.md`, `docs/VIEWER_HANDOFF.md`.

## Highlight colors

`viewer/src/lib/highlight-colors.ts` is the single source of truth.
EmbedPDF gets the same array via the `colorPresets` config in
`EmbedPDFView.svelte`. There's a stale-but-harmless svelte-check warning
about the `readonly` tuple — ignore unless you're cleaning the
type-error list.

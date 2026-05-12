# Viewer architecture

The Viewer is a Tauri 2 desktop app with a Svelte 5 frontend. PDFs render via [EmbedPDF](https://github.com/embedpdf/embedpdf), notes via CodeMirror 6. The Rust backend handles filesystem watching and a few sandboxed Tauri commands.

## Where things live

```
viewer/
├── src-tauri/        Rust backend (Tauri commands, vault filesystem watcher)
│   ├── main.rs
│   └── src/vault.rs  read_annotations / write_annotations / file watching
└── src/              Svelte frontend
    ├── App.svelte
    ├── lib/          shared utilities (incl. highlight-colors.ts)
    ├── state/        Svelte runes / stores (incl. library.svelte.ts)
    └── panes/        UI components — see below
```

Key panes:

| Component | Purpose |
|---|---|
| `Library.svelte` | Left pane — paper list, search, filters, **MANUSCRIPTS** section (papers tagged `cite:*`). |
| `TabContent.svelte` | The middle/right split — one tab per open paper. |
| `EmbedPDFView.svelte` | EmbedPDF host: opens the document, mounts plugins, wires the annotation sidecar (load + debounced save). |
| `EmbedPdfToolbar.svelte` | Page navigation, zoom, find, annotate-mode toggle. |
| `EmbedPageAnnotations.svelte` | Per-page `<Annotations>` wrapper. Pulls the live scale from `useZoom`. |
| `EmbedHighlightSelectionMenu.svelte` | Color picker that pops on text-select to create a highlight. |
| `EmbedAnnotationSelectionMenu.svelte` | Delete/edit menu that pops on annotation-select. |
| `EmbedAnnotationKeybinds.svelte` | Global Delete/Backspace listener for annotation removal. |
| `NoteEditor.svelte` | Right pane. CodeMirror 6 editor + rendered Markdown preview. ⌘⇧N inserts a timestamped section. |
| `CollectionsPanel.svelte` | Drag-drop collection editing (visible in the Organizing mode). |
| `PDFView.svelte` | Legacy pdfjs-based reader. Still in tree behind `localStorage.setItem('vault.embedPdf', '1')` toggle; EmbedPDF is the default. |

## Annotation pipeline

Highlights are stored as `Annotations/{citekey}.json` — EmbedPDF's native `AnnotationTransferItem[]` JSON, written verbatim. XFDF conversion is deferred to export time.

Non-obvious wiring that's easy to break:

### `<Annotations>` requires `<RendererRegistryProvider>` above it

The provider's Svelte context carries the built-in renderers (Highlight, Underline, FreeText, …). Without the provider, the overlay component mounts but renders nothing. `EmbedPDFView.svelte` wraps the whole `<Viewport>` / `<Scroller>` tree in the provider.

### `<Annotations>` scale comes from `useZoom`, not `page.scale`

The Scroller's `renderPage` snippet hands a `PageLayout` (pageNumber, pageIndex, width, height, rotatedWidth) — no `scale` / `rotation`. If you pass `<Annotations scale={1} …>`, overlays drift relative to the underlying text at any zoom ≠ 100%.

The fix lives in `EmbedPageAnnotations.svelte`: a thin per-page wrapper that calls `useZoom(() => documentId)` and feeds the live `currentZoomLevel` into `<Annotations scale={…}>`. `useZoom` only works inside the EmbedPDF plugin tree, which is why this is a child component instead of a top-level read.

### PDFium tile renders exclude annotations on purpose

PDFium worker renders use `withAnnotations: false` — visible highlights come **only** from our overlay. `autoCommit: true` writes annotations into the in-memory PDF (so they round-trip cleanly into XFDF later) but the tile renderer ignores them.

If `<Annotations>` ever stops mounting, all highlights vanish visually even though the data is intact in `state.byUid`.

### Baseline filter (so the sidecar stays clean)

A PDF may already contain embedded annotations (one test paper had 3,321 — publisher links, prior reader highlights, etc.). On the `loaded` event we snapshot all annotation IDs as the **baseline**, then `importAnnotations` from the sidecar. On every save we filter the export to exclude baseline IDs, so the sidecar only ever contains the user's own highlights.

Without this filter, the sidecar grows to multi-megabyte JSON full of the PDF's pre-existing annotations.

### Two selection-menu snippets

Two unrelated "selection menus" exist in EmbedPDF; we wire both:

| Layer | Triggered by | Our component | Purpose |
|---|---|---|---|
| `SelectionLayer` | text selection | `EmbedHighlightSelectionMenu.svelte` | Create highlights |
| `<Annotations>` | annotation selection | `EmbedAnnotationSelectionMenu.svelte` | Delete/edit existing |

They take different `context` types (`SelectionContext` vs `AnnotationSelectionContext`) — don't conflate them.

## Highlight colors

`viewer/src/lib/highlight-colors.ts` is the single source of truth. EmbedPDF gets the same array via the `colorPresets` config in `EmbedPDFView.svelte`. There's a known harmless svelte-check warning about the `readonly` tuple — ignore unless you're cleaning the type-error list.

## Vite HMR gotcha

When you create a new `.svelte` file (especially under `panes/`), Vite's HMR sometimes doesn't pick it up — the component imports fine to TS but doesn't mount at runtime. Hard reload (Cmd+Shift+R) or restart `npm run tauri dev`. If you're unsure a new component is mounting, add a temporary `border: 2px dashed red` so you can see it.

## Backend (Rust)

`viewer/src-tauri/src/vault.rs` exposes the Tauri commands the frontend calls:

- `read_annotations` / `write_annotations` — load and persist `Annotations/{citekey}.json`.
- Vault filesystem watcher (via the `notify` crate) — emits Tauri events when external processes (the Librarian, ad-hoc scripts) modify the vault, so the Viewer reloads.
- Drag-drop handler — accepts dropped PDFs, hands them to `file_paper.py`.

Tauri's asset protocol is scoped to `$HOME/**` so the sandboxed frontend can read vault files.

# Viewer

The macOS desktop app. Tauri 2 + Svelte 5 + EmbedPDF + CodeMirror 6.

- **Building / installing:** see [tutorial: getting started](../docs/tutorial/getting-started.md) step 2.
- **Architecture & internals:** [reference: viewer architecture](../docs/reference/viewer-architecture.md).
- **Updating after a `git pull`:** [how-to: update the Viewer](../docs/how-to/update-the-viewer.md).
- **Things that don't work yet:** [Known limitations](../docs/KNOWN_LIMITATIONS.md).

## Dev quickstart

```bash
npm install
npm run tauri dev
```

Set `localStorage.setItem('vault.embedPdf', '1')` in the dev console to toggle the EmbedPDF-based reader (currently the default in the built app).
